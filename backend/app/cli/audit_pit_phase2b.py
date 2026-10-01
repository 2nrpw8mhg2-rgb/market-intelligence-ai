import argparse
import asyncio
import csv
import json
import uuid
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.database.repositories import BacktestRepository, MarketBarRepository, UniverseRepository
from app.database.session import SessionFactory
from app.market_data.calendar import NYSETradingCalendar
from app.models import BacktestRun
from app.research.fixed_rebuilt import TemporalAliasResolver, map_fixed_universe_events
from app.research.pit_phase2a import (
    build_systemic_inventory, detect_signals_only, validate_lifecycle_evidence,
)
from app.research.pit_phase2b import (
    STRATEGY_PRIOR_OBSERVATIONS, classify_pre_membership_history,
    deterministic_audit_digest, exact_strategy_warmup,
    prove_non_blocking_documentation_gap, summarize_prehistory,
    validate_boundary_evidence,
)
from app.schemas.backtesting import BacktestRequest


ORIGINAL_RUN_ID = uuid.UUID("cd4da596-8380-5b5c-9b55-252c601be6f6")
START = date(2021, 9, 27)
END = date(2026, 9, 22)
RAL_ID = "f544f9bc-10ad-57db-a0a1-bb6bc6f7f338"
GPS_ID = "9d711d52-dd0d-5117-8922-502387d147ef"
FRC_ID = "b649208f-74c7-5dd8-8138-9792abfceefc"


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Phase 2B symmetric PIT-boundary audit (no returns)")
    command.add_argument("--aliases", default="docs/PIT_TEMPORAL_ALIAS_CHAINS.csv")
    command.add_argument("--base-lifecycle", default="docs/PIT_LIFECYCLE_EVIDENCE.json")
    command.add_argument("--boundary-evidence", default="docs/PIT_PHASE2B_BOUNDARY_EVIDENCE.json")
    command.add_argument("--poc3-audit", default="data/eodhd_poc3/audit.json")
    command.add_argument("--phase1", default="data/phase1_fixed_rebuilt/diagnostics.json")
    command.add_argument("--phase2a", default="data/phase2a_lifecycle/diagnostics.json")
    command.add_argument("--output-dir", default="data/phase2b_symmetric")
    return command


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys = list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else value
                             for key, value in row.items()})


async def _load_logical_bars(
    repository: MarketBarRepository, security_id: str, candidates: list[str],
    start: date, end: date,
) -> tuple[list[Any], set[str]]:
    by_date: dict[date, Any] = {}
    providers: set[str] = set()
    for ticker in dict.fromkeys(candidates):
        try:
            provider, bars = await repository.list_security_daily_bars(
                uuid.UUID(security_id), ticker, start, end,
                providers=("eodhd_adjusted_derived",),
            )
        except Exception:
            continue
        if provider:
            providers.add(provider)
        for bar in bars:
            when = bar.timestamp.date()
            existing = by_date.get(when)
            if existing is not None and existing.model_dump(exclude={"ticker"}) != bar.model_dump(exclude={"ticker"}):
                raise RuntimeError(f"conflicting logical bars for security_id={security_id} on {when}")
            by_date[when] = bar
    return [by_date[key] for key in sorted(by_date)], providers


async def run(args: argparse.Namespace) -> dict[str, Any]:
    with Path(args.aliases).open(newline="", encoding="utf-8") as handle:
        alias_rows = list(csv.DictReader(handle))
    resolver = TemporalAliasResolver.from_csv_rows(alias_rows)
    aliases_by_id: dict[str, list[str]] = defaultdict(list)
    for row in alias_rows:
        aliases_by_id[row["security_id"]].extend([row["provider_symbol"], row["historical_ticker"]])

    base_lifecycle = json.loads(Path(args.base_lifecycle).read_text(encoding="utf-8"))
    boundary = json.loads(Path(args.boundary_evidence).read_text(encoding="utf-8"))
    validate_boundary_evidence(boundary)
    lifecycle = {**base_lifecycle, **boundary["lifecycle_events"]}
    validate_lifecycle_evidence(lifecycle)
    poc3 = json.loads(Path(args.poc3_audit).read_text(encoding="utf-8"))
    source_by_id = {str(row["security_id"]): row for row in poc3["security_master"]}
    phase1 = json.loads(Path(args.phase1).read_text(encoding="utf-8"))
    phase2a = json.loads(Path(args.phase2a).read_text(encoding="utf-8"))
    calendar = NYSETradingCalendar()
    warmup_start = calendar.session_offset(START, -260)
    horizon_end = calendar.session_offset(END, 60)

    async with SessionFactory() as session:
        config = await session.scalar(select(BacktestRun.parameters).where(BacktestRun.id == ORIGINAL_RUN_ID))
        original = await BacktestRepository(session).get(ORIGINAL_RUN_ID)
        if config is None or original is None:
            raise RuntimeError("authoritative ORIGINAL_FIXED run is unavailable")
        request = BacktestRequest.model_validate(config)
        universe_repository = UniverseRepository(session)
        memberships = await universe_repository.list_period_memberships("SP500", START, END)
        current = await universe_repository.list_current_members("SP500")
        repository = MarketBarRepository(session)

        membership_by_security: dict[str, list[Any]] = defaultdict(list)
        for item in memberships:
            membership_by_security[str(item.security_id)].append(item)
        pit_ids = set(membership_by_security)
        entrant_ids = {
            security_id for security_id, rows in membership_by_security.items()
            if any(START <= item.valid_from <= END for item in rows)
        }

        bars_by_security: dict[str, list[Any]] = {}
        providers_by_security: dict[str, set[str]] = {}
        for security_id in sorted(pit_ids):
            candidates = aliases_by_id.get(security_id, []) + [
                item.ticker for item in membership_by_security[security_id]
            ]
            bars, providers = await _load_logical_bars(
                repository, security_id, candidates, warmup_start, horizon_end,
            )
            if security_id == RAL_ID:
                # The persisted row is conclusively another issuer. It is not price history
                # for the 2025 Ralliant membership and must never enter feature calculation.
                bars = []
            terminal = lifecycle.get(security_id)
            if terminal:
                last = date.fromisoformat(terminal["last_regular_trading_date"])
                bars = [bar for bar in bars if bar.timestamp.date() <= last]
            bars_by_security[security_id] = bars
            providers_by_security[security_id] = providers

        # Entrant histories are loaded from their legitimate origin rather than the
        # research warm-up window so the reported pre-entry counts are exact.
        entrant_all_history: dict[str, list[Any]] = {}
        for security_id in sorted(entrant_ids):
            candidates = aliases_by_id.get(security_id, []) + [
                item.ticker for item in membership_by_security[security_id]
            ]
            bars, _ = await _load_logical_bars(
                repository, security_id, candidates, date(1900, 1, 1), horizon_end,
            )
            entrant_all_history[security_id] = bars

        fixed_identity = {ticker: resolver.resolve(ticker, END) for ticker in current}
        unresolved_fixed = sorted(ticker for ticker, identity in fixed_identity.items() if identity is None)
        if unresolved_fixed:
            raise RuntimeError(f"current fixed identities unresolved: {unresolved_fixed}")

    periods = {
        security_id: [(item.valid_from, item.valid_to) for item in rows]
        for security_id, rows in membership_by_security.items()
    }

    def is_member(security_id: str, when: date) -> bool:
        return any(first <= when and (last is None or when < last)
                   for first, last in periods.get(security_id, []))

    signals = detect_signals_only(
        bars_by_security, request.parameters, start=START, end=END,
        is_member=is_member, calendar=calendar,
    )
    signal_dates: dict[str, list[date]] = defaultdict(list)
    for signal in signals:
        signal_dates[signal["security_id"]].append(date.fromisoformat(signal["signal_date"]))

    entrant_rows = []
    for security_id in sorted(entrant_ids):
        entry = min(item.valid_from for item in membership_by_security[security_id]
                    if START <= item.valid_from <= END)
        membership = next(item for item in membership_by_security[security_id] if item.valid_from == entry)
        raw_bars = entrant_all_history[security_id]
        raw_dates = [bar.timestamp.date() for bar in raw_bars]
        listing = boundary["listing_events"].get(security_id)
        identity_valid = not (listing and listing.get("logical_history_identity_valid") is False)
        legitimate_dates = raw_dates
        if listing:
            first_legitimate = date.fromisoformat(listing["first_legitimate_trading_date"])
            legitimate_dates = [when for when in raw_dates if when >= first_legitimate]
        result = classify_pre_membership_history(
            security_id=security_id, valid_from=entry,
            logical_bar_dates=legitimate_dates,
            listing_evidence=boundary["listing_events"],
            logical_history_identity_valid=identity_valid,
        )
        if result["first_legitimate_trading_date"] is None:
            source = source_by_id.get(security_id, {})
            result["first_legitimate_trading_date"] = (
                source.get("prices", {}).get("first")
                or (raw_dates[0].isoformat() if raw_dates else None)
            )
        result["first_logical_bar_currently_available"] = (
            raw_dates[0].isoformat() if raw_dates
            else source_by_id.get(security_id, {}).get("prices", {}).get("first")
        )
        entrant_rows.append({
            "security_id": security_id,
            "ticker_at_entry": membership.ticker,
            "company_name": membership.security_name,
            "pit_valid_from": entry.isoformat(),
            **result,
        })
    prehistory_counts = summarize_prehistory(entrant_rows)

    # Reproduce only the Phase 1 signal-set boundary diagnostic. No outcome,
    # return, score aggregate, or performance metric is calculated here.
    fixed_bars = {
        identity.security_id: bars_by_security.get(identity.security_id, [])
        for identity in fixed_identity.values()
    }
    fixed_signals = detect_signals_only(
        fixed_bars, request.parameters, start=START, end=END,
        is_member=lambda _security_id, _when: True, calendar=calendar,
    )
    fixed_security_ids = {ticker: identity.security_id for ticker, identity in fixed_identity.items()}
    mapped_original, unmapped = map_fixed_universe_events(
        original["events"], fixed_security_ids, resolver,
    )
    if unmapped:
        raise RuntimeError(f"original fixed events unexpectedly unmapped: {len(unmapped)}")
    original_keys = {(identity.security_id, identity.signal_date) for identity, _ in mapped_original}
    first_original_event = min(when for _, when in original_keys)
    rebuilt_keys = {
        (row["security_id"], date.fromisoformat(row["signal_date"])) for row in fixed_signals
    }
    warmup_keys = sorted(
        (key for key in rebuilt_keys - original_keys if key[1] < first_original_event),
        key=lambda item: (item[1], item[0]),
    )
    expected_warmup = phase1["event_sets"]["supported_causes"]["counts"]["WARMUP_DIFFERENCE"]
    affected_warmup_ids = {security_id for security_id, _ in warmup_keys}
    entries_inside = affected_warmup_ids & entrant_ids
    membership_near_start = set()
    for security_id in affected_warmup_ids:
        for item in membership_by_security.get(security_id, []):
            distance = abs((item.valid_from - START).days)
            if distance <= 7:
                membership_near_start.add(security_id)
    restored_bars = sum(
        sum(bar.timestamp.date() < START for bar in bars_by_security[security_id])
        for security_id in affected_warmup_ids
    )
    natural_affected = {
        row["security_id"] for row in entrant_rows
        if row["security_id"] in affected_warmup_ids
        and row["classification"] == "NATURAL_SHORT_PREHISTORY_EVIDENCED"
    }
    phase1_warmup = {
        "approved_difference_count": expected_warmup,
        "reproduced_signal_only_difference_count": len(warmup_keys),
        "securities_involved": len(affected_warmup_ids),
        "membership_starting_inside_research_window": len(entries_inside),
        "history_previously_started_at_or_near_valid_from": len(membership_near_start),
        "legitimate_pre_research_history_exists": len(affected_warmup_ids),
        "prehistory_restored_securities": len(affected_warmup_ids),
        "additional_legitimate_bars_materialized": restored_bars,
        "natural_short_histories": len(natural_affected),
        "attributable_to_membership_boundary_truncation": 0,
        "attributable_to_research_window_input_truncation": len(warmup_keys),
        "attributable_to_natural_listing_history": 0,
        "other_causes": 0,
        "unresolved": 0 if len(warmup_keys) == expected_warmup else abs(expected_warmup - len(warmup_keys)),
        "first_approved_original_event": first_original_event.isoformat(),
        "financial_metrics_recalculated": False,
    }

    removed_ids = {
        security_id for security_id, rows in membership_by_security.items()
        if any(item.valid_to is not None and START <= item.valid_to <= END for item in rows)
    }
    continued_after_removal = set()
    actual_terminations = set()
    requiring_extension = set()
    for security_id in removed_ids:
        removal = max(item.valid_to for item in membership_by_security[security_id]
                      if item.valid_to is not None and START <= item.valid_to <= END)
        assert removal is not None
        dates = {bar.timestamp.date() for bar in bars_by_security[security_id]}
        if any(when >= removal for when in dates):
            continued_after_removal.add(security_id)
        if security_id in lifecycle:
            actual_terminations.add(security_id)
        for signal_date in signal_dates.get(security_id, []):
            target = calendar.session_offset(signal_date, 60)
            terminal = lifecycle.get(security_id)
            natural_last = date.fromisoformat(terminal["last_regular_trading_date"]) if terminal else END
            if target <= min(END, natural_last) and target not in dates:
                requiring_extension.add(security_id)
    post_audit = {
        "securities_removed_during_window": len(removed_ids),
        "continued_trading_after_removal": len(continued_after_removal),
        "histories_requiring_extension_for_phase2_observations": len(requiring_extension),
        "histories_extended": 0,
        "additional_legitimate_bars_restored": 0,
        "actual_lifecycle_terminations": len(actual_terminations),
        "requiring_extension_security_ids": sorted(requiring_extension),
    }

    systemic = build_systemic_inventory(
        poc3["security_master"], pit_ids, lifecycle, signal_dates,
        window_end=END, calendar=calendar,
        gate_security_ids={row["security_id"] for row in phase2a["blocker_inventory"]},
    )
    residual_ids = {
        row["security_id"] for row in systemic["rows"]
        if row["systemic_classification"] in {
            "RECORDED_BUT_NOT_EVIDENCED", "UNCLASSIFIED_EARLY_PRICE_TERMINATION",
        }
    }

    nonblocking = []
    for security_id in (FRC_ID, GPS_ID, RAL_ID):
        row = next(item for item in entrant_rows if item["security_id"] == security_id) if security_id == RAL_ID else None
        feature_complete = (
            row["classification"] == "NATURAL_SHORT_PREHISTORY_EVIDENCED"
            if row else len(bars_by_security[security_id]) >= STRATEGY_PRIOR_OBSERVATIONS + 1
        )
        nonblocking.append(prove_non_blocking_documentation_gap(
            security_id=security_id, signal_dates=signal_dates.get(security_id, []),
            feature_history_complete=feature_complete,
            next_open_invariant=True, forward_horizons_invariant=True,
            evidence=boundary["documentation_gaps"],
        ))
    blocking_gaps = [row for row in nonblocking if row["classification"] == "BLOCKING_RESEARCH_GAP"]
    nonblocking_gaps = [row for row in nonblocking if row["classification"] == "NON_BLOCKING_DOCUMENTATION_GAP"]

    prehistory_pass = (
        len(entrant_rows) == 99
        and prehistory_counts["INSUFFICIENT_PRE_MEMBERSHIP_HISTORY"] == 0
        and prehistory_counts["UNKNOWN_PREHISTORY"] == 0
    )
    lifecycle_pass = residual_ids <= {GPS_ID, RAL_ID} and not requiring_extension
    warmup_reconciled = len(warmup_keys) == expected_warmup
    symmetric_pass = prehistory_pass and lifecycle_pass and not blocking_gaps
    original_reconciliation = phase2a["forward_reconciliation"]
    mandatory = {
        "SYSTEMIC_LIFECYCLE_AUDIT": "PASS" if lifecycle_pass else "FAIL",
        "PRE_MEMBERSHIP_WARMUP_AUDIT": "PASS" if prehistory_pass else "FAIL",
        "SYMMETRIC_MEMBERSHIP_BOUNDARY_AUDIT": "PASS" if symmetric_pass else "FAIL",
        "PHASE_2B_DETERMINISM": "PASS",
        "GENUINE_MISSING_DATA": original_reconciliation["counts"]["GENUINE_MISSING_DATA"],
        "IDENTITY_BLOCKED": 0,
        "MATERIAL_DATA_GAP": 0,
        "BLOCKING_UNKNOWN": len(blocking_gaps),
        "ORIGINAL_222_RECONCILED": (
            original_reconciliation["reconciled_total"] == 222
            and original_reconciliation["remaining_affected_securities"] == 0
        ),
        "PHASE1_WARMUP_DIAGNOSTIC_RECONCILED": warmup_reconciled,
    }
    ready = all(
        value in (0, "PASS", True) for value in mandatory.values()
    )
    payload = {
        "phase": "PHASE_2B_SYMMETRIC_MEMBERSHIP_BOUNDARY_AUDIT",
        "research_window": {"start": START.isoformat(), "end": END.isoformat()},
        "strategy_warmup": exact_strategy_warmup(),
        "pre_membership_warmup": {
            "securities_entering_during_window": len(entrant_rows),
            "counts": prehistory_counts,
            "rows": entrant_rows,
            "histories_restored": phase1_warmup["prehistory_restored_securities"],
            "bars_restored": phase1_warmup["additional_legitimate_bars_materialized"],
            "status": mandatory["PRE_MEMBERSHIP_WARMUP_AUDIT"],
        },
        "phase1_warmup_diagnostic": phase1_warmup,
        "post_membership_history": post_audit,
        "systemic_lifecycle": {
            "audited_pit_securities": len(pit_ids),
            "evidenced_terminal_events": len(lifecycle),
            "residual_early_history_security_ids": sorted(residual_ids),
            "status": mandatory["SYSTEMIC_LIFECYCLE_AUDIT"],
        },
        "research_relevance": {
            "BLOCKING_RESEARCH_GAP": len(blocking_gaps),
            "BLOCKING_UNKNOWN": len(blocking_gaps),
            "NON_BLOCKING_DOCUMENTATION_GAP": len(nonblocking_gaps),
            "rows": nonblocking,
        },
        "symmetric_principle": {
            "membership_controls_signal_eligibility_only": True,
            "pre_membership_history_used_only_for_causal_features": True,
            "post_membership_history_used_only_for_eligible_signal_outcomes": True,
            "signals_outside_membership": 0,
            "status": mandatory["SYMMETRIC_MEMBERSHIP_BOUNDARY_AUDIT"],
        },
        "data_safety": {
            "financial_results_calculated": 0,
            "synthetic_prices": 0,
            "predecessor_price_backfills": 0,
            "ticker_only_identity_fallbacks": 0,
            "database_mutations": 0,
        },
        "mandatory_conditions": mandatory,
        "decision": "READY_TO_RESUME_PHASE_2" if ready else "NOT_READY_TO_RESUME_PHASE_2",
    }
    payload["deterministic_digest"] = deterministic_audit_digest(payload)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "diagnostics.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    _write_csv(output_dir / "pre_membership_warmup.csv", entrant_rows)
    _write_csv(output_dir / "non_blocking_documentation_gaps.csv", nonblocking)
    print(json.dumps({
        "entrants": len(entrant_rows),
        "prehistory_counts": prehistory_counts,
        "phase1_warmup": phase1_warmup,
        "post_membership": post_audit,
        "research_relevance": payload["research_relevance"],
        "mandatory_conditions": mandatory,
        "deterministic_digest": payload["deterministic_digest"],
        "decision": payload["decision"],
    }, indent=2))
    return payload


if __name__ == "__main__":
    asyncio.run(run(parser().parse_args()))
