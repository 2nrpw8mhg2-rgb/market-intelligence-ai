import argparse
import asyncio
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from app.cli.common import emit_report
from app.core.config import get_settings
from app.eodhd import EODHDClient
from app.eodhd.audit import coverage_diagnostics, snapshot_diagnostics
from app.eodhd.identity import (
    Confidence, ReuseStatus, StartDateStatus, build_symbol_change_graph,
    classify_null_start, name_similarity, reuse_status, split_adjusted_signal_series,
    stable_security_id,
)
from app.eodhd.models import HistoricalConstituent
from app.market_data.calendar import NYSETradingCalendar

COVERAGE_START = date(2012, 4, 1)
SNAPSHOTS = [date(2013, 6, 28), date(2016, 6, 30), date(2020, 6, 30), date(2022, 6, 30), date(2026, 6, 30)]
CRITICAL = ("FB", "META", "MON", "ATVI", "TWTR", "SIVB", "CELG", "LEH", "AAL")


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="POC 2: historical identity and membership resolution")
    command.add_argument("--output", default="data/eodhd_poc2/audit.json")
    command.add_argument("--cache-dir", default="data/eodhd_poc/cache")
    return command


async def safe(awaitable, errors: list[dict], context: str):
    try:
        return await awaitable
    except Exception as exc:
        errors.append({"context": context, "error_type": type(exc).__name__, "message": str(exc)[:240]})
        return None


def general_identifiers(general: dict[str, Any]) -> dict[str, str]:
    return {key: str(general[key]) for key in ("CIK", "CUSIP", "ISIN", "OpenFigi", "LEI") if general.get(key)}


def confidence_for(identifiers: dict[str, str], reuse: ReuseStatus) -> Confidence:
    if reuse is ReuseStatus.TICKER_REUSE_CONFIRMED:
        return Confidence.UNRESOLVED
    if len(identifiers) >= 2 and reuse is ReuseStatus.NO_REUSE_EVIDENCE:
        return Confidence.HIGH
    if identifiers and reuse is not ReuseStatus.UNRESOLVED:
        return Confidence.MEDIUM
    if reuse is ReuseStatus.NO_REUSE_EVIDENCE:
        return Confidence.LOW
    return Confidence.UNRESOLVED


def snapshot_resolution(records: list[HistoricalConstituent], session: date) -> dict[str, Any]:
    raw = snapshot_diagnostics(records, session)
    # PRE_HISTORY_MEMBER is an evidence status, not a fabricated StartDate. The
    # existing interval already treated NULL as an open lower bound, so it adds 0.
    return {"date": session, "raw_count": raw["constituents"],
            "after_safe_resolution": raw["constituents"], "added": [],
            "duplicates": raw["duplicates"], "unresolved_null_start_in_snapshot": raw["missing_start_date"]}


def boundary_audit(records: list[HistoricalConstituent]) -> list[dict[str, Any]]:
    by_start: dict[date, list[str]] = defaultdict(list)
    for item in records:
        if item.start_date:
            by_start[item.start_date].append(item.code)
    selected = []
    for former in records:
        if former.end_date and former.end_date in by_start:
            before = former.end_date - timedelta(days=1)
            after = former.end_date + timedelta(days=1)
            selected.append({
                "end_date": former.end_date, "removed": former.code,
                "starters_same_date": sorted(by_start[former.end_date]),
                "h1_inclusive_count": len([item for item in records if item.is_member_on(former.end_date, end_date_inclusive=True)]),
                "h2_exclusive_count": len([item for item in records if item.is_member_on(former.end_date, end_date_inclusive=False)]),
                "count_day_before_h2": len([item for item in records if item.is_member_on(before, end_date_inclusive=False)]),
                "count_day_after_h2": len([item for item in records if item.is_member_on(after, end_date_inclusive=False)]),
            })
    critical = [item for item in selected if item["removed"] in {"ATVI", "TWTR", "SIVB", "CELG", "AAL"}]
    others = [item for item in selected if item not in critical][:10]
    return critical + others


def split_validation(symbol: str, bars, splits) -> list[dict[str, Any]]:
    adjusted = {item["date"]: item for item in split_adjusted_signal_series(bars, splits)}
    raw = {bar.date: bar for bar in bars}
    sessions = sorted(raw)
    results = []
    for split in splits:
        if not split.split or split.date not in raw:
            continue
        index = sessions.index(split.date)
        if index == 0:
            continue
        previous = sessions[index - 1]
        volumes = [raw[day].volume for day in sessions[max(0, index - 20):index]]
        results.append({
            "symbol": symbol, "split_date": split.date, "ratio": split.split,
            "raw_close_return": raw[split.date].close / raw[previous].close - 1,
            "split_adjusted_close_return": adjusted[split.date]["close"] / adjusted[previous]["close"] - 1,
            "relative_volume_vs_prior_20": raw[split.date].volume / float(np.mean(volumes)) if volumes else None,
            "volume_policy": "EODHD volume already split-adjusted; no synthetic factor applied",
        })
    return results


async def run(args: argparse.Namespace) -> None:
    settings = get_settings()
    client = EODHDClient(api_key=settings.eodhd_api_key.get_secret_value(), base_url=settings.eodhd_base_url,
        timeout_seconds=settings.eodhd_timeout_seconds, max_retries=settings.eodhd_max_retries,
        retry_base_seconds=settings.eodhd_retry_base_seconds, cache_dir=Path(args.cache_dir))
    errors: list[dict] = []
    records = await client.historical_constituents()
    changes = await client.symbol_changes(date(2012, 1, 1), date(2026, 9, 28))
    delisted = await client.delisted_symbols()
    current_payload = await client.historical_snapshot(date(2026, 6, 30))
    current_rows = next(iter(current_payload.values()), {}) if current_payload else {}
    current = {str(row.get("Code", "")).upper(): row for row in current_rows.values()}
    delisted_by_code = {str(row.get("Code", "")).upper(): row for row in delisted}
    null_records = [item for item in records if item.start_date is None]

    null_audit = []
    null_prices = {}
    fundamentals = {}
    changes_by_symbol: dict[str, list[dict]] = defaultdict(list)
    for change in changes:
        payload = change.model_dump(mode="json")
        changes_by_symbol[change.old_symbol].append(payload)
        changes_by_symbol[change.new_symbol].append(payload)
    for index, record in enumerate(null_records, 1):
        general = await safe(client.fundamentals_general(f"{record.code}.US"), errors, f"fundamentals:{record.code}") or {}
        bars = await safe(client.eod(f"{record.code}.US"), errors, f"eod:{record.code}") or []
        fundamentals[record.code] = general
        null_prices[record.code] = bars
        identifiers = general_identifiers(general)
        reference_name = general.get("Name") or delisted_by_code.get(record.code, {}).get("Name")
        reuse = reuse_status(record.name, reference_name)
        null_audit.append({
            "ticker": record.code, "membership_name": record.name, "end_date": record.end_date,
            "is_delisted": record.is_delisted, "status": classify_null_start(record, COVERAGE_START),
            "resolution_bound": f"before {COVERAGE_START.isoformat()}",
            "fundamentals_available": bool(general), "fundamentals_name": general.get("Name"),
            "identifiers": identifiers, "symbol_changes": changes_by_symbol.get(record.code, []),
            "first_eod": bars[0].date if bars else None, "last_eod": bars[-1].date if bars else None,
            "reuse_status": reuse, "confidence": confidence_for(identifiers, reuse),
            "evidence": ["StartDate NULL in provider membership log; exact date not imputed"],
        })

    # Confirm the known Monsanto alias offered by the delisted directory before
    # screening the complete membership feed.  The historical membership row's
    # MON name has been overwritten by a later issuer, so name-only matching
    # would otherwise produce a false negative for ticker reuse.
    monsanto_entry = next((row for row in delisted if "monsanto" in str(row.get("Name", "")).lower()), None)

    # Whole-feed reuse screen uses batch directories; it intentionally does not
    # claim identity where no independent reference is available.
    reuse_audit = []
    for record in records:
        reference = current.get(record.code) or delisted_by_code.get(record.code)
        reference_name = reference.get("Name") if reference else None
        status = (ReuseStatus.TICKER_REUSE_CONFIRMED
                  if record.code == "MON" and monsanto_entry
                  else reuse_status(record.name, reference_name))
        reuse_audit.append({"ticker": record.code, "membership_name": record.name,
                            "reference_name": reference_name, "status": status,
                            "name_similarity": name_similarity(record.name, reference_name) if reference_name else None})

    # Confirm the known Monsanto alias offered by the delisted directory.
    mon_bars = []
    mon_general = {}
    if monsanto_entry:
        mon_code = str(monsanto_entry["Code"])
        mon_bars = await safe(client.eod(f"{mon_code}.US"), errors, f"eod:{mon_code}") or []
        mon_general = await safe(client.fundamentals_general(f"{mon_code}.US"), errors, f"fundamentals:{mon_code}") or {}
    else:
        mon_code = None

    by_code = {item.code: item for item in records}
    sample_codes = [code for code in ("AAPL", "NVDA", "META", "AAL", "ATVI", "SIVB", "TWTR", "MON", "CELG", "GE") if code in by_code]
    before_prices = {}
    for code in sample_codes:
        if code in null_prices:
            before_prices[code] = null_prices[code]
        else:
            record = by_code[code]
            before_prices[code] = await safe(client.eod(f"{code}.US", max(record.start_date or COVERAGE_START, date(2012, 1, 1)),
                                                        min(record.end_date or date(2026, 9, 22), date(2026, 9, 22))),
                                             errors, f"sample_eod:{code}") or []
    before_records = [by_code[code] for code in sample_codes]
    before = coverage_diagnostics(before_records, before_prices, date(2012, 1, 1), date(2026, 9, 22))
    after_prices = dict(before_prices)
    if mon_bars:
        after_prices["MON"] = mon_bars
    after = coverage_diagnostics(before_records, after_prices, date(2012, 1, 1), date(2026, 9, 22))
    after_exclusive = coverage_diagnostics(
        before_records, after_prices, date(2012, 1, 1), date(2026, 9, 22),
        end_date_inclusive=False,
    )

    split_checks = []
    for code in ("AAPL", "NVDA", "GE"):
        bars = before_prices[code]
        splits = await client.splits(f"{code}.US", date(2012, 1, 1), date(2026, 9, 22))
        split_checks.extend(split_validation(code, bars, splits))

    critical_timelines = {
        "FB_META": {"symbol_changes": changes_by_symbol.get("META", []),
                    "finding": "FB current lookup is a reused ETF; META identifiers identify Meta Platforms"},
        "MON": {"membership": by_code["MON"].model_dump(mode="json"), "resolved_alias": mon_code,
                "delisted_entry": monsanto_entry, "resolved_identifiers": general_identifiers(mon_general),
                "first_eod": mon_bars[0].date if mon_bars else None, "last_eod": mon_bars[-1].date if mon_bars else None,
                "finding": "MON_old is the Monsanto series; current/delisted MON is a different security"},
    }

    terminal = {
        "ATVI": {"classification": "ACQUISITION", "tradeability": "ends before membership EndDate", "terminal_value": "UNKNOWN"},
        "TWTR": {"classification": "ACQUISITION", "tradeability": "ends before membership EndDate", "terminal_value": "UNKNOWN"},
        "CELG": {"classification": "ACQUISITION", "tradeability": "ends before membership EndDate", "terminal_value": "UNKNOWN"},
        "SIVB": {"classification": "BANKRUPTCY", "tradeability": "NASDAQ series ends; OTC successor identifier observed", "terminal_value": "UNKNOWN"},
        "LEH": {"classification": "BANKRUPTCY", "tradeability": "no EOD in audit window", "terminal_value": "UNKNOWN"},
        "MON": {"classification": "ACQUISITION", "tradeability": "resolved to MON_old alias", "terminal_value": "UNKNOWN"},
        "AAL": {"classification": "INDEX_REMOVAL_STILL_TRADING", "tradeability": "continues after membership", "terminal_value": "NOT_APPLICABLE"},
    }

    graph = build_symbol_change_graph([item.model_dump(mode="json") for item in changes])
    membership_codes = {item.code for item in records}
    relevant_changes = [item for item in changes
                        if item.old_symbol in membership_codes or item.new_symbol in membership_codes]
    relevant_graph = build_symbol_change_graph([item.model_dump(mode="json") for item in relevant_changes])

    counts = Counter(item["confidence"] for item in null_audit)
    reuse_counts = Counter(item["status"] for item in reuse_audit)
    report = {
        "scope": "POC2_IDENTITY_MEMBERSHIP_NO_BACKTEST", "as_of": date(2026, 9, 28),
        "requests": {"network": client.metrics.network_requests, "cache_hits": client.metrics.cache_hits,
                     "rate_limits": client.metrics.rate_limit_events},
        "null_start": {"total": len(null_records), "status_counts": Counter(item["status"] for item in null_audit),
                       "confidence_counts": counts, "records": null_audit},
        "snapshots": [snapshot_resolution(records, item) for item in SNAPSHOTS],
        "boundaries": boundary_audit(records),
        "identity": {"audited_membership_tickers": len(reuse_audit), "reuse_counts": reuse_counts,
                     "independently_enriched_records": len(null_audit),
                     "independent_enrichment_confidence": counts,
                     "external_reused_aliases_not_present_as_membership_rows": ["FB"],
                     "records": reuse_audit, "critical_timelines": critical_timelines},
        "symbol_change_graph": {"whole_us_feed": graph, "membership_relevant": relevant_graph},
        "terminal_events": terminal,
        "coverage": {"before": before, "after_identity_inclusive": after,
                     "after_identity_and_exclusive_end_date": after_exclusive,
                     "resolution_effect": "MON membership mapped to MON_old only; no other missing bar synthesized"},
        "split_signal_series_validation": split_checks,
        "errors": errors,
    }
    emit_report(report, args.output)


if __name__ == "__main__":
    asyncio.run(run(parser().parse_args()))
