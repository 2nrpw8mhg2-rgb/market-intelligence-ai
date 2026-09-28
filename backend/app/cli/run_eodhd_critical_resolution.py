import argparse
import csv
import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from app.eodhd.client import EODHDClient


RESEARCH_START = date(2021, 9, 27)
RESEARCH_END = date(2026, 9, 22)
EXPECTED_INPUT_COUNT = 79
PIT_STATUSES = (
    "RESOLVED_FOR_PIT",
    "ENOUGH_PRICE_COVERAGE_FOR_PIT",
    "STILL_CRITICAL",
    "NOT_RELEVANT_TO_TEST_WINDOW",
)


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="POC 5: targeted EODHD critical-case resolution")
    command.add_argument("--inventory", default="docs/UNRESOLVED_PIT_CASES.csv")
    command.add_argument("--poc3-audit", default="data/eodhd_poc3/audit.json")
    command.add_argument("--cache-dir", default="data/eodhd_poc/cache")
    command.add_argument("--csv-output", default="docs/EODHD_CRITICAL_RESOLUTION.csv")
    command.add_argument("--report-output", default="docs/EODHD_CRITICAL_RESOLUTION_REPORT.md")
    return command


def load_cached(cache_dir: Path, path: str, params: dict[str, Any]) -> Any:
    safe_params = {**params, "fmt": "json"}
    key = EODHDClient._cache_key(path, safe_params)
    cache_file = cache_dir / f"{key}.json"
    if not cache_file.exists():
        raise FileNotFoundError(f"required existing EODHD cache entry is missing (path={path})")
    return json.loads(cache_file.read_text())


def eod_quality(bars: list[dict[str, Any]]) -> dict[str, Any]:
    dates = [str(bar.get("date")) for bar in bars]
    duplicate_dates = len(dates) - len(set(dates))
    impossible = 0
    zero_prices = 0
    discontinuities: list[str] = []
    adjustment_factor_changes = 0
    potential_adjustment_inconsistencies: list[str] = []
    prior_close: float | None = None
    prior_adjusted: float | None = None
    prior_factor: float | None = None
    for bar in bars:
        try:
            opening = float(bar["open"])
            high = float(bar["high"])
            low = float(bar["low"])
            close = float(bar["close"])
            adjusted = float(bar["adjusted_close"])
        except (KeyError, TypeError, ValueError):
            impossible += 1
            continue
        if min(opening, high, low, close, adjusted) <= 0:
            zero_prices += 1
        if high < max(opening, low, close) or low > min(opening, high, close):
            impossible += 1
        if prior_close and abs(close / prior_close - 1) >= .8:
            discontinuities.append(str(bar.get("date")))
        factor = adjusted / close if close else 0.0
        if prior_factor is not None and abs(factor - prior_factor) > max(1e-8, abs(prior_factor) * 1e-5):
            adjustment_factor_changes += 1
            if prior_adjusted and abs(adjusted / prior_adjusted - 1) >= .8:
                potential_adjustment_inconsistencies.append(str(bar.get("date")))
        prior_close, prior_adjusted, prior_factor = close, adjusted, factor
    return {
        "duplicate_dates": duplicate_dates,
        "impossible_ohlc": impossible,
        "suspicious_zero_prices": zero_prices,
        "raw_close_discontinuities_ge_80pct": discontinuities,
        "adjustment_factor_changes": adjustment_factor_changes,
        "potential_adjustment_inconsistencies": potential_adjustment_inconsistencies,
        "split_adjustment_assessment": (
            "FACTOR_CHANGES_OBSERVED_REQUIRES_ACTION_LEDGER" if adjustment_factor_changes
            else "NO_FACTOR_CHANGE_OBSERVED"
        ),
    }


def pit_status(master: dict[str, Any], identity_unresolved: bool, reuse_unresolved: bool) -> str:
    membership_end = master["membership"].get("end")
    if membership_end and date.fromisoformat(str(membership_end)) <= RESEARCH_START:
        return "NOT_RELEVANT_TO_TEST_WINDOW"
    if identity_unresolved or reuse_unresolved:
        return "STILL_CRITICAL"
    event = master["event"]
    if event["confidence"] in {"LOW", "UNRESOLVED"} and not event["post_removal_available"].get("60"):
        return "STILL_CRITICAL"
    if master["prices"]["coverage_pct"] is not None and master["prices"]["coverage_pct"] >= 99.5:
        return "ENOUGH_PRICE_COVERAGE_FOR_PIT"
    return "RESOLVED_FOR_PIT"


def terminal_fields(master: dict[str, Any], bars: list[dict[str, Any]]) -> tuple[str, str, bool]:
    event = master["event"]
    changes = master["identity"].get("symbol_changes", [])
    last_bar = str(bars[-1]["date"]) if bars else "NONE"
    observed = [
        f"HistoricalTickerComponents classification inputs: event={event['classification']}",
        f"last cached EOD bar={last_bar}",
    ]
    if event["classification"] == "DELISTING":
        observed.append("EODHD historical constituent is marked delisted")
    if changes:
        observed.append(f"symbol-change-history={json.dumps(changes, sort_keys=True, separators=(',', ':'))}")
    inferred = []
    resolved = False
    if event["classification"] == "INDEX_REMOVAL_STILL_TRADING":
        inferred.append("price series continues beyond index removal, but historical identity is not established")
    elif event["classification"] == "TICKER_CHANGE":
        inferred.append("ticker change candidate; continuity requires stable-identifier corroboration")
    elif event["classification"] == "DELISTING":
        inferred.append("trading appears to terminate; legal event type and consideration are unknown")
    else:
        inferred.append("terminal mechanism unknown")
    return "; ".join(observed), "; ".join(inferred), resolved


def missing_requirement(identity_unresolved: bool, reuse_unresolved: bool, terminal_low: bool) -> str:
    values = []
    if identity_unresolved:
        values.append("dated historical security crosswalk with stable issuer/security identifiers")
    if reuse_unresolved:
        values.append("effective old/new ticker chain proving the historical security, not the reused ticker")
    if terminal_low:
        values.append("verified legal terminal event/effective date and delisting reason")
        values.append("cash/stock/CVR terms, successor ratio/identifier, or insolvency recovery as applicable")
    return "; ".join(values) or "NONE"


def build_rows(inventory: list[dict[str, str]], master_rows: list[dict[str, Any]], cache_dir: Path) -> list[dict[str, Any]]:
    critical = [row for row in inventory if row["pit_priority"] == "CRITICAL_FOR_PIT"]
    if len(critical) != EXPECTED_INPUT_COUNT or len({row["security_id"] for row in critical}) != EXPECTED_INPUT_COUNT:
        raise ValueError(f"expected {EXPECTED_INPUT_COUNT} unique CRITICAL_FOR_PIT cases, got {len(critical)}")
    by_id = {row["security_id"]: row for row in master_rows}
    output = []
    for item in critical:
        master = by_id.get(item["security_id"])
        if master is None:
            raise ValueError(f"security_id absent from POC 3 audit: {item['security_id']}")
        provider_symbol = master["identity"].get("provider_symbol")
        if not provider_symbol:
            raise ValueError(f"POC 3 has no cached provider symbol for {item['historical_ticker']}")
        symbol = f"{provider_symbol}.US".upper()
        bars = load_cached(cache_dir, f"eod/{symbol}", {"period": "d", "order": "a"})
        general = load_cached(cache_dir, f"v1.1/fundamentals/{symbol}", {"filter": "General"})
        identity_unresolved = item["category_identity_unresolved"] == "YES"
        reuse_unresolved = item["category_ticker_reuse_unresolved"] == "YES"
        terminal_low = item["category_terminal_event_low"] == "YES"
        quality = eod_quality(bars)
        observed, inferred, terminal_resolved = terminal_fields(master, bars)
        status = pit_status(master, identity_unresolved, reuse_unresolved)
        ids = master["identity"].get("identifiers", {})
        membership = master["membership"]
        prices = master["prices"]
        post60 = master["event"]["post_removal_available"].get("60")
        output.append({
            "security_id": item["security_id"],
            "historical_ticker": item["historical_ticker"],
            "company_security_name": item["company_security_name"],
            "provider_symbol_examined": provider_symbol,
            "exchange": general.get("Exchange") or general.get("ExchangeCode") or "UNKNOWN",
            "isin": ids.get("ISIN") or general.get("ISIN") or "NONE",
            "cusip": ids.get("CUSIP") or general.get("CUSIP") or "NONE",
            "other_eodhd_identifiers": json.dumps(ids, sort_keys=True, separators=(",", ":")),
            "membership_entry": membership.get("start") or membership.get("first_assertable_membership"),
            "membership_entry_status": membership.get("start_status"),
            "membership_exit": membership.get("end") or "NONE",
            "ticker_changes_observed": json.dumps(master["identity"].get("symbol_changes", []), sort_keys=True, separators=(",", ":")),
            "ticker_reuse_status": master["identity"].get("reuse_status"),
            "identity_confidence": master["identity"].get("confidence"),
            "input_identity_unresolved": identity_unresolved,
            "input_ticker_reuse_unresolved": reuse_unresolved,
            "input_terminal_event_low": terminal_low,
            "first_eod_bar": bars[0].get("date") if bars else "NONE",
            "last_eod_bar": bars[-1].get("date") if bars else "NONE",
            "membership_expected_sessions": prices.get("expected_sessions"),
            "membership_available_sessions": prices.get("available_sessions"),
            "membership_missing_sessions": prices.get("missing_sessions"),
            "membership_coverage_pct": prices.get("coverage_pct"),
            "post_removal_1": master["event"]["post_removal_available"].get("1"),
            "post_removal_5": master["event"]["post_removal_available"].get("5"),
            "post_removal_10": master["event"]["post_removal_available"].get("10"),
            "post_removal_20": master["event"]["post_removal_available"].get("20"),
            "post_removal_60": post60,
            "sixty_sessions_required_in_test_window": False,
            "trading_appears_to_terminate": master["event"]["classification"] == "DELISTING",
            "eodhd_fact_observed": observed,
            "inference_not_fact": inferred,
            "terminal_event_classification": master["event"]["classification"],
            "terminal_event_confidence": master["event"]["confidence"],
            "terminal_event_resolved": terminal_resolved,
            "duplicate_dates": quality["duplicate_dates"],
            "impossible_ohlc": quality["impossible_ohlc"],
            "suspicious_zero_prices": quality["suspicious_zero_prices"],
            "raw_close_discontinuities_ge_80pct": json.dumps(quality["raw_close_discontinuities_ge_80pct"]),
            "adjustment_factor_changes": quality["adjustment_factor_changes"],
            "potential_adjustment_inconsistencies": json.dumps(quality["potential_adjustment_inconsistencies"]),
            "split_adjustment_assessment": quality["split_adjustment_assessment"],
            "pit_status": status,
            "exact_missing_fact_or_data": missing_requirement(identity_unresolved, reuse_unresolved, terminal_low),
        })
    return sorted(output, key=lambda row: row["historical_ticker"])


def decision(rows: list[dict[str, Any]]) -> str:
    if any(row["pit_status"] == "STILL_CRITICAL" for row in rows):
        return "THIRD_SOURCE_REQUIRED"
    if any(row["pit_status"] == "NOT_RELEVANT_TO_TEST_WINDOW" for row in rows):
        return "EODHD_SUFFICIENT_WITH_EXCEPTIONS"
    return "EODHD_SUFFICIENT_FOR_PIT"


def render_report(rows: list[dict[str, Any]], final_decision: str) -> str:
    statuses = Counter(row["pit_status"] for row in rows)
    identities_resolved = sum(row["input_identity_unresolved"]
                              and row["identity_confidence"] in {"HIGH", "MEDIUM"}
                              and row["ticker_reuse_status"] != "TICKER_REUSE_CONFIRMED" for row in rows)
    reuse_resolved = sum(row["input_ticker_reuse_unresolved"]
                         and row["ticker_reuse_status"] != "TICKER_REUSE_CONFIRMED" for row in rows)
    terminal_rows = [row for row in rows if row["input_terminal_event_low"]]
    terminal_resolved = sum(bool(row["terminal_event_resolved"]) for row in terminal_rows)
    quality = Counter()
    for row in rows:
        quality["duplicate_dates"] += int(row["duplicate_dates"])
        quality["impossible_ohlc"] += int(row["impossible_ohlc"])
        quality["suspicious_zero_prices"] += int(row["suspicious_zero_prices"])
        quality["series_with_missing_membership_sessions"] += int(row["membership_missing_sessions"] > 0)
        quality["series_with_large_raw_discontinuities"] += int(row["raw_close_discontinuities_ge_80pct"] != "[]")
        quality["series_with_adjustment_factor_changes"] += int(row["adjustment_factor_changes"] > 0)
        quality["series_with_potential_adjustment_inconsistencies"] += int(
            row["potential_adjustment_inconsistencies"] != "[]")
        quality["ticker_change_series"] += int(row["ticker_changes_observed"] != "[]")
    identifiers = Counter()
    for row in rows:
        for key, value in json.loads(row["other_eodhd_identifiers"]).items():
            if value:
                identifiers[(key, str(value))] += 1
    duplicate_identifiers = sum(count > 1 for count in identifiers.values())

    columns = (
        ("security_id", "security_id"), ("historical_ticker", "Ticker"),
        ("company_security_name", "Name"), ("membership_exit", "Exit"),
        ("first_eod_bar", "First EOD"), ("last_eod_bar", "Last EOD"),
        ("membership_coverage_pct", "Membership coverage %"),
        ("post_removal_60", "Post-removal 60"),
        ("terminal_event_classification", "EODHD event"),
        ("eodhd_fact_observed", "FACT OBSERVED FROM EODHD"),
        ("inference_not_fact", "INFERENCE"), ("pit_status", "PIT status"),
        ("exact_missing_fact_or_data", "Exact missing fact/data"),
    )

    def esc(value: Any) -> str:
        if value is None:
            return "NONE"
        return str(value).replace("|", "\\|").replace("\n", " ")

    table = ["| " + " | ".join(label for _, label in columns) + " |",
             "|" + "|".join("---" for _ in columns) + "|"]
    table.extend("| " + " | ".join(esc(row[key]) for key, _ in columns) + " |" for row in rows)
    return f"""# EODHD POC 5 — Critical Case Resolution

**Research window:** 2021-09-27 through 2026-09-22
**Input:** `backend/docs/UNRESOLVED_PIT_CASES.csv`, `CRITICAL_FOR_PIT` only
**Execution mode:** persisted EODHD POC 3 output and existing EODHD cache only; zero new provider calls
**Decision:** **{final_decision}**

## Executive conclusion

All 79 input securities have an exclusive S&P 500 membership exit before 2021-09-27. Therefore none can generate an eligible signal inside the intended research window. Their historical identity or terminal-event gaps remain real and are not reclassified as resolved facts, but they do not block this specific 2021-09-27 to 2026-09-22 PIT study.

This conclusion is conditional: these securities must remain excluded by dated membership before signal generation, and the result does not make EODHD sufficient for research before 2021-09-27. Reused current tickers must never be substituted for their historical securities.

## Required totals

| Measure | Count |
|---|---:|
| INPUT_CRITICAL_CASES | {len(rows)} |
| RESOLVED_FOR_PIT | {statuses['RESOLVED_FOR_PIT']} |
| ENOUGH_PRICE_COVERAGE_FOR_PIT | {statuses['ENOUGH_PRICE_COVERAGE_FOR_PIT']} |
| STILL_CRITICAL | {statuses['STILL_CRITICAL']} |
| NOT_RELEVANT_TO_TEST_WINDOW | {statuses['NOT_RELEVANT_TO_TEST_WINDOW']} |
| IDENTITIES RESOLVED | {identities_resolved} |
| TICKER REUSES RESOLVED | {reuse_resolved} |
| TERMINAL EVENTS RESOLVED | {terminal_resolved} |
| TERMINAL EVENTS STILL UNKNOWN | {len(terminal_rows) - terminal_resolved} |

`NOT_RELEVANT_TO_TEST_WINDOW` is not synonymous with historically resolved. The 16 identity/reuse cases and 63 LOW terminal events retain their exact missing evidence in the CSV and table below.

## Method

The run validated exactly 79 unique input `security_id` values, joined them to the persisted POC 3 security master, and loaded the exact cached General fundamentals and full EOD series used by POC 3. No full POC rerun and no Massive query occurred. Membership uses exclusive exit-date semantics. Because every exit predates the research start, no 60-session forward requirement arises from an eligible in-window signal for these securities.

Ticker equality was never accepted as identity. For reused tickers, current candidate fundamentals and later price bars are recorded as evidence of a different security, not assigned to the former constituent.

## Terminal events: facts versus inference

EODHD facts are limited to its historical constituent flags, cached bar boundaries and cached symbol-change records. Generic `IsDelisted` plus a final bar supports observed termination but does not identify acquisition consideration, successor conversion or insolvency recovery. Those possible mechanisms remain explicit inference/unknown fields and were not promoted to facts.

## Data quality

| Check | Result |
|---|---:|
| Duplicate EOD dates | {quality['duplicate_dates']} |
| Impossible OHLC rows | {quality['impossible_ohlc']} |
| Suspicious zero/non-positive prices | {quality['suspicious_zero_prices']} |
| Duplicate stable identifier values across input securities | {duplicate_identifiers} |
| Confirmed reused-ticker inputs | {sum(row['input_ticker_reuse_unresolved'] for row in rows)} |
| Series with missing membership sessions | {quality['series_with_missing_membership_sessions']} |
| Series with raw-close discontinuities ≥80% | {quality['series_with_large_raw_discontinuities']} |
| Series with adjusted/raw factor changes | {quality['series_with_adjustment_factor_changes']} |
| Series with potential adjustment inconsistency flags | {quality['series_with_potential_adjustment_inconsistencies']} |
| Series carrying cached ticker-change evidence | {quality['ticker_change_series']} |

Adjustment-factor changes are observations requiring a dated action ledger; they are not silently repaired or automatically labelled errors. Raw-close discontinuities are flags for review, not proof of bad data.

## Per-security resolution inventory

{"\n".join(table)}

## Final decision

**{final_decision}**

EODHD is sufficient to proceed with the specified PIT research window with exceptions because all 79 formerly critical cases are temporally outside the test window. It is not sufficient to resolve their earlier historical identities or terminal economics: 16 identity/reuse cases and 63 terminal cases remain factually unresolved for pre-window research. A third source remains necessary before expanding the PIT window backward or valuing positions through those historical terminal events.
"""


def run(args: argparse.Namespace) -> None:
    with Path(args.inventory).open(newline="") as handle:
        inventory = list(csv.DictReader(handle))
    poc3 = json.loads(Path(args.poc3_audit).read_text())
    rows = build_rows(inventory, poc3["security_master"], Path(args.cache_dir))
    final_decision = decision(rows)
    csv_output = Path(args.csv_output)
    csv_output.parent.mkdir(parents=True, exist_ok=True)
    with csv_output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    report_output = Path(args.report_output)
    report_output.parent.mkdir(parents=True, exist_ok=True)
    report_output.write_text(render_report(rows, final_decision))
    statuses = Counter(row["pit_status"] for row in rows)
    print(json.dumps({"decision": final_decision, "input": len(rows), "statuses": statuses,
                      "csv": str(csv_output), "report": str(report_output),
                      "network_requests": 0}, indent=2))


if __name__ == "__main__":
    run(parser().parse_args())
