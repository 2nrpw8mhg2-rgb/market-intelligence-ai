import hashlib
import json
from collections import Counter, defaultdict
from datetime import date
from typing import Any, Callable, Iterable

import pandas as pd

from app.features import FeatureEngine
from app.schemas.market_data import MarketBar
from app.schemas.scanner import BreakoutStrategyParameters
from app.strategies import BreakoutVolumeStrategy


LIFECYCLE_REASONS = {"ACQUISITION", "MERGER", "BANKRUPTCY", "DELISTING_OTHER"}
SYSTEMIC_CLASSES = (
    "EVIDENCED_LIFECYCLE_TERMINATION",
    "RECORDED_BUT_NOT_EVIDENCED",
    "UNCLASSIFIED_EARLY_PRICE_TERMINATION",
    "NATURAL_DATASET_BOUNDARY",
    "OTHER_EXPLAINED",
)
RECONCILIATION_CLASSES = (
    "SECURITY_LIFECYCLE_TRUNCATION",
    "PROVIDER_GAP_RESOLVED",
    "ALIAS_CONTINUITY_RESOLVED",
    "TEMPORARY_HALT",
    "GENUINE_MISSING_DATA",
    "UNKNOWN",
)


def _valid_bar(bar: MarketBar) -> bool:
    return (
        bar.open > 0 and bar.high > 0 and bar.low > 0 and bar.close > 0
        and bar.volume >= 0 and bar.high >= bar.low
        and bar.low <= bar.open <= bar.high and bar.low <= bar.close <= bar.high
    )


def classify_observation_gap(
    *, expected_sessions: list[date], primary_bars: list[MarketBar],
    alternative_bars: list[MarketBar], identity_proven: bool,
    proven_temporary_halt: bool = False,
) -> str:
    """Classify without merging, filling, interpolating, or manufacturing any bar."""
    primary_dates = {bar.timestamp.date() for bar in primary_bars}
    missing = [session for session in expected_sessions if session not in primary_dates]
    if not missing:
        return "COMPLETE"
    if proven_temporary_halt and any(session > max(missing) for session in primary_dates):
        return "TEMPORARY_HALT"
    alternative = {bar.timestamp.date(): bar for bar in alternative_bars}
    if (identity_proven and all(session in alternative for session in missing)
            and all(_valid_bar(alternative[session]) for session in missing)):
        return "PROVIDER_GAP_RESOLVED"
    return "GENUINE_MISSING_DATA"


def parse_date(value: str | date | None) -> date | None:
    if value is None or value == "":
        return None
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def validate_lifecycle_evidence(evidence: dict[str, dict[str, Any]]) -> None:
    for security_id, item in evidence.items():
        reason = item.get("classification")
        if reason not in LIFECYCLE_REASONS:
            raise ValueError(f"unsupported lifecycle classification for {security_id}: {reason}")
        last = parse_date(item.get("last_regular_trading_date"))
        close = parse_date(item.get("closing_date"))
        if last is None or close is None or last > close:
            raise ValueError(f"invalid lifecycle chronology for {security_id}")
        if item.get("confidence") != "HIGH" or not item.get("sources"):
            raise ValueError(f"lifecycle evidence is not auditable for {security_id}")


def classify_signal_timing(
    signal_date: date, announcement_date: date, last_regular_trading_date: date,
) -> str:
    if signal_date < announcement_date:
        return "PRE_ANNOUNCEMENT"
    if signal_date == announcement_date:
        return "ON_ANNOUNCEMENT_DATE"
    if signal_date <= last_regular_trading_date:
        return "POST_ANNOUNCEMENT_PRE_CLOSE"
    return "POST_CLOSE_INVALID"


def classify_next_open_executability(
    *, signal_date: date, next_expected_session: date,
    available_sessions: set[date], last_regular_trading_date: date,
) -> str:
    if next_expected_session in available_sessions and next_expected_session <= last_regular_trading_date:
        return "EXECUTABLE_WITH_COMPLETE_HORIZON"
    if last_regular_trading_date <= signal_date and next_expected_session > last_regular_trading_date:
        return "NON_EXECUTABLE_LIFECYCLE_TERMINATION"
    if any(session > next_expected_session for session in available_sessions):
        return "GENUINE_MISSING_DATA"
    return "UNKNOWN"


def detect_signals_only(
    bars_by_security: dict[str, list[MarketBar]], parameters: BreakoutStrategyParameters,
    *, start: date, end: date,
    is_member: Callable[[str, date], bool], calendar: Any,
) -> list[dict[str, Any]]:
    """Detect eligible signals causally without reading outcomes or computing returns."""
    strategy = BreakoutVolumeStrategy(parameters)
    signals: list[dict[str, Any]] = []
    for security_id in sorted(bars_by_security):
        bars = bars_by_security[security_id]
        if len(bars) < 200:
            continue
        frame = FeatureEngine().calculate(pd.DataFrame([bar.model_dump() for bar in bars]))
        available = {bar.timestamp.date(): bar for bar in bars}
        for _, series in frame.iterrows():
            signal_date = series["timestamp"].date()
            if not start <= signal_date <= end or not is_member(security_id, signal_date):
                continue
            row = series.to_dict()
            required = ("SMA_200", "PREVIOUS_HIGH_20D", "RELATIVE_VOLUME", "MOMENTUM_20D")
            if any(pd.isna(row.get(key)) for key in required):
                continue
            accepted, _ = strategy.evaluate(row)
            if not accepted:
                continue
            next_session = calendar.session_offset(signal_date, 1)
            signals.append({
                "security_id": security_id,
                "signal_date": signal_date.isoformat(),
                "signal_close": float(row["close"]),
                "next_expected_session": next_session.isoformat(),
                "next_open_available": next_session in available,
            })
    return sorted(signals, key=lambda item: (item["signal_date"], item["security_id"]))


def reconcile_forward_cases(
    cases: Iterable[dict[str, Any]], evidence: dict[str, dict[str, Any]], calendar: Any,
) -> dict[str, Any]:
    """Reconcile the original immutable gap universe; never creates price observations."""
    validate_lifecycle_evidence(evidence)
    rows = []
    unique_by_class: dict[str, set[tuple[str, date]]] = {
        key: set() for key in RECONCILIATION_CLASSES
    }
    for case in cases:
        security_id = str(case["security_id"])
        first = date.fromisoformat(str(case["first_missing_session"]))
        last = date.fromisoformat(str(case["last_missing_session"]))
        missing = calendar.trading_days_between(first, last)
        if len(missing) != int(case["missing_sessions"]):
            raise ValueError(f"missing-session inventory is not contiguous for {security_id}")
        item = evidence.get(security_id)
        if item is None:
            classification = "UNKNOWN"
        else:
            terminal = parse_date(item["last_regular_trading_date"])
            assert terminal is not None
            classification = (
                "SECURITY_LIFECYCLE_TRUNCATION"
                if all(session > terminal for session in missing)
                else "GENUINE_MISSING_DATA"
            )
        for session in missing:
            unique_by_class[classification].add((security_id, session))
        rows.append({**case, "reconciliation_classification": classification,
                     "lifecycle_reason": item.get("classification") if item else None})
    counts = {key: len(value) for key, value in unique_by_class.items()}
    return {
        "cases": rows,
        "affected_event_horizons": len(rows),
        "affected_securities": len({row["security_id"] for row in rows}),
        "counts": counts,
        "reconciled_total": sum(counts.values()),
    }


def classify_early_history(
    row: dict[str, Any], evidence: dict[str, dict[str, Any]], *, window_end: date,
) -> tuple[str, str | None]:
    last = parse_date(row.get("prices", {}).get("last"))
    if last is None:
        return "OTHER_EXPLAINED", None
    if last >= window_end:
        return "NATURAL_DATASET_BOUNDARY", None
    security_id = str(row["security_id"])
    if security_id in evidence:
        return "EVIDENCED_LIFECYCLE_TERMINATION", evidence[security_id]["classification"]
    event = row.get("event", {})
    if event.get("classification") in {"DELISTING", "TICKER_CHANGE"}:
        return "RECORDED_BUT_NOT_EVIDENCED", None
    return "UNCLASSIFIED_EARLY_PRICE_TERMINATION", None


def build_systemic_inventory(
    security_master: Iterable[dict[str, Any]], pit_security_ids: set[str],
    evidence: dict[str, dict[str, Any]], signal_dates: dict[str, list[date]],
    *, window_end: date, calendar: Any, gate_security_ids: set[str],
) -> dict[str, Any]:
    validate_lifecycle_evidence(evidence)
    rows = []
    for source in security_master:
        security_id = str(source["security_id"])
        if security_id not in pit_security_ids:
            continue
        logical_last = parse_date(source.get("prices", {}).get("last"))
        if logical_last is None or logical_last >= window_end:
            continue
        category, reason = classify_early_history(source, evidence, window_end=window_end)
        lifecycle = evidence.get(security_id, {})
        last_legitimate = parse_date(lifecycle.get("last_regular_trading_date"))
        effective_last = last_legitimate or logical_last
        assert effective_last is not None
        dates = sorted(signal_dates.get(security_id, []))
        near_start = calendar.session_offset(effective_last, -60)
        near = [item for item in dates if near_start <= item <= effective_last]
        membership = source["membership"]
        rows.append({
            "security_id": security_id,
            "final_ticker": membership["ticker"],
            "company_name": source.get("canonical_name"),
            "membership_start": membership.get("start") or membership.get("first_assertable_membership"),
            "membership_end": membership.get("end"),
            "final_logical_price_history_date": logical_last.isoformat(),
            "last_legitimate_trading_date": effective_last.isoformat(),
            "lifecycle_reason": reason,
            "lifecycle_effective_date": lifecycle.get("closing_date"),
            "evidence_source": (
                lifecycle.get("sources", [{}])[0].get("url")
                if lifecycle else None
            ),
            "evidence_confidence": lifecycle.get("confidence") or source.get("event", {}).get("confidence"),
            "explicit_in_lifecycle_ledger": bool(lifecycle),
            "generated_pit_signal": bool(dates),
            "signals_within_60_sessions": len(near),
            "triggered_phase2_gate": security_id in gate_security_ids,
            "systemic_classification": category,
            "source_event_classification": source.get("event", {}).get("classification"),
        })
    rows.sort(key=lambda item: (item["last_legitimate_trading_date"], item["security_id"]))
    counts = Counter(row["systemic_classification"] for row in rows)
    reasons = Counter(row["lifecycle_reason"] for row in rows if row["lifecycle_reason"])
    years: dict[str, Counter] = {str(year): Counter() for year in range(2021, 2027)}
    for row in rows:
        year = row["last_legitimate_trading_date"][:4]
        if year not in years:
            continue
        years[year]["total"] += 1
        category = row["systemic_classification"]
        if category == "EVIDENCED_LIFECYCLE_TERMINATION":
            years[year]["evidenced"] += 1
        elif category == "RECORDED_BUT_NOT_EVIDENCED":
            years[year]["recorded_but_not_evidenced"] += 1
        elif category == "UNCLASSIFIED_EARLY_PRICE_TERMINATION":
            years[year]["unclassified"] += 1
    return {
        "rows": rows,
        "counts": {key: counts[key] for key in SYSTEMIC_CLASSES},
        "reasons": {key: reasons[key] for key in sorted(LIFECYCLE_REASONS)},
        "by_year": {year: dict(values) for year, values in years.items()},
        "status": "PASS" if all(counts[key] == 0 for key in (
            "RECORDED_BUT_NOT_EVIDENCED", "UNCLASSIFIED_EARLY_PRICE_TERMINATION"
        )) else "FAIL",
    }


def build_mna_signal_ledger(
    signals: Iterable[dict[str, Any]], evidence: dict[str, dict[str, Any]],
    alias_for: Callable[[str, date], str | None],
) -> dict[str, Any]:
    rows = []
    for signal in signals:
        security_id = str(signal["security_id"])
        lifecycle = evidence.get(security_id)
        if lifecycle is None or lifecycle["classification"] not in {"ACQUISITION", "MERGER"}:
            continue
        when = date.fromisoformat(str(signal["signal_date"]))
        announcement = date.fromisoformat(lifecycle["announcement_date"])
        last = date.fromisoformat(lifecycle["last_regular_trading_date"])
        rows.append({
            "security_id": security_id,
            "ticker_at_signal_date": alias_for(security_id, when),
            "signal_date": when.isoformat(),
            "transaction_announcement_date": announcement.isoformat(),
            "last_regular_trading_date": last.isoformat(),
            "transaction_closing_date": lifecycle["closing_date"],
            "transaction_type": lifecycle["transaction_type"],
            "announced_cash_consideration": lifecycle.get("cash_consideration"),
            "announced_stock_consideration": lifecycle.get("stock_consideration"),
            "contingent_consideration": lifecycle.get("contingent_consideration"),
            "non_tradable_component": bool(lifecycle.get("non_tradable_component")),
            "timing_classification": classify_signal_timing(when, announcement, last),
        })
    rows.sort(key=lambda item: (item["signal_date"], item["security_id"]))
    timings = Counter(row["timing_classification"] for row in rows)
    securities = {row["security_id"] for row in rows}
    transactions = Counter(evidence[item]["transaction_type"] for item in securities)
    return {
        "rows": rows,
        "signal_counts": {key: timings[key] for key in (
            "PRE_ANNOUNCEMENT", "ON_ANNOUNCEMENT_DATE",
            "POST_ANNOUNCEMENT_PRE_CLOSE", "POST_CLOSE_INVALID",
        )},
        "affected_securities": len(securities),
        "transaction_counts": {key: transactions[key] for key in ("CASH", "STOCK", "MIXED", "OTHER")},
        "transactions_with_contingent_or_non_tradable_consideration": sum(
            bool(evidence[item].get("contingent_consideration")
                 or evidence[item].get("non_tradable_component"))
            for item in securities
        ),
    }


def deterministic_audit_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
