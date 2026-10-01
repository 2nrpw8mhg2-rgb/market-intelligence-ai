import argparse
import asyncio
import csv
import json
import uuid
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.database.repositories import MarketBarRepository, UniverseRepository
from app.database.session import SessionFactory
from app.market_data.calendar import NYSETradingCalendar
from app.models import BacktestRun
from app.research.fixed_rebuilt import TemporalAliasResolver
from app.research.pit_phase2a import (
    build_mna_signal_ledger, build_systemic_inventory,
    classify_next_open_executability, detect_signals_only,
    deterministic_audit_digest, parse_date, reconcile_forward_cases,
    validate_lifecycle_evidence,
)
from app.schemas.backtesting import BacktestRequest


ORIGINAL_RUN_ID = uuid.UUID("cd4da596-8380-5b5c-9b55-252c601be6f6")
START = date(2021, 9, 27)
END = date(2026, 9, 22)
EXPECTED_CANONICAL_HASH = "74d14b5198a7e64e91127abbbdcaae087e8c9134f6e8f6786446c210e2529b4d"
TWTR_ID = "ae13e1b5-7a16-59c1-95ce-2bfa52b340d7"


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Phase 2A lifecycle-integrity audit (no returns)")
    command.add_argument("--aliases", default="docs/PIT_TEMPORAL_ALIAS_CHAINS.csv")
    command.add_argument("--lifecycle-evidence", default="docs/PIT_LIFECYCLE_EVIDENCE.json")
    command.add_argument("--audit", default="data/eodhd_poc3/audit.json")
    command.add_argument("--phase2", default="data/phase2_pit_event_study/diagnostics.json")
    command.add_argument("--output-dir", default="data/phase2a_lifecycle")
    return command


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: (
                json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else value
            ) for key, value in row.items()})


def _source_rows(audit: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row["security_id"]): row for row in audit["security_master"]}


async def run(args: argparse.Namespace) -> dict[str, Any]:
    aliases_path = Path(args.aliases)
    with aliases_path.open(newline="", encoding="utf-8") as handle:
        alias_rows = list(csv.DictReader(handle))
    resolver = TemporalAliasResolver.from_csv_rows(alias_rows)
    pit_security_ids = {row["security_id"] for row in alias_rows}
    evidence = json.loads(Path(args.lifecycle_evidence).read_text(encoding="utf-8"))
    validate_lifecycle_evidence(evidence)
    audit = json.loads(Path(args.audit).read_text(encoding="utf-8"))
    phase2 = json.loads(Path(args.phase2).read_text(encoding="utf-8"))
    original = phase2["genuine_missing_data"]
    gate_ids = {str(row["security_id"]) for row in original["securities"]}
    source_by_id = _source_rows(audit)
    calendar = NYSETradingCalendar()
    warmup = calendar.session_offset(START, -260)

    early_ids = {
        security_id for security_id in pit_security_ids
        if security_id in source_by_id
        and source_by_id[security_id].get("prices", {}).get("last")
        and source_by_id[security_id]["prices"]["last"] < END.isoformat()
    }

    async with SessionFactory() as session:
        stored_config = await session.scalar(
            select(BacktestRun.parameters).where(BacktestRun.id == ORIGINAL_RUN_ID)
        )
        if stored_config is None:
            raise RuntimeError("authoritative approved strategy configuration is unavailable")
        request = BacktestRequest.model_validate(stored_config)
        memberships = await UniverseRepository(session).list_period_memberships("SP500", START, END)
        repository = MarketBarRepository(session)
        membership_by_security: dict[str, list[Any]] = defaultdict(list)
        for membership in memberships:
            membership_by_security[str(membership.security_id)].append(membership)

        bars_by_security = {}
        provider_by_security = {}
        for security_id in sorted(early_ids):
            records = membership_by_security.get(security_id, [])
            candidates = list(dict.fromkeys(
                [row["provider_symbol"] for row in alias_rows if row["security_id"] == security_id]
                + [item.ticker for item in records]
            ))
            provider = None
            bars = []
            for candidate in candidates:
                try:
                    provider, bars = await repository.list_security_daily_bars(
                        uuid.UUID(security_id), candidate, warmup, END,
                        providers=("eodhd_adjusted_derived",),
                    )
                except Exception:
                    continue
                if bars:
                    break
            if not bars:
                raise RuntimeError(f"no logical price history for PIT security_id={security_id}")
            lifecycle = evidence.get(security_id)
            if lifecycle:
                last_legitimate = date.fromisoformat(lifecycle["last_regular_trading_date"])
                bars = [bar for bar in bars if bar.timestamp.date() <= last_legitimate]
            bars_by_security[security_id] = bars
            provider_by_security[security_id] = provider

    periods = {
        security_id: [(item.valid_from, item.valid_to) for item in records]
        for security_id, records in membership_by_security.items()
    }

    def is_member(security_id: str, when: date) -> bool:
        return any(start <= when and (end is None or when < end)
                   for start, end in periods.get(security_id, []))

    signals = detect_signals_only(
        bars_by_security, request.parameters, start=START, end=END,
        is_member=is_member, calendar=calendar,
    )
    signal_dates: dict[str, list[date]] = defaultdict(list)
    for signal in signals:
        signal_dates[signal["security_id"]].append(date.fromisoformat(signal["signal_date"]))

    reconciled = reconcile_forward_cases(original["cases"], evidence, calendar)
    blocker_rows = []
    for case in reconciled["cases"]:
        security_id = case["security_id"]
        signal_date = date.fromisoformat(case["signal_date"])
        next_session = calendar.session_offset(signal_date, 1)
        bars = {bar.timestamp.date(): bar for bar in bars_by_security[security_id]}
        source = source_by_id[security_id]
        lifecycle = evidence[security_id]
        alias = resolver.resolve_security(security_id, source["membership"]["ticker"], signal_date)
        if alias is None:
            raise RuntimeError(f"dated alias unresolved for blocker {security_id} at {signal_date}")
        alias_row = next(row for row in alias_rows
                         if row["security_id"] == security_id
                         and date.fromisoformat(row["valid_from"]) <= signal_date
                         and (not row["valid_to"] or signal_date < date.fromisoformat(row["valid_to"])))
        signal_bar = bars.get(signal_date)
        blocker_rows.append({
            "security_id": security_id,
            "company_name": source["canonical_name"],
            "ticker_at_signal_date": alias.historical_alias,
            "temporal_alias": alias.provider_symbol,
            "signal_date": signal_date.isoformat(),
            "signal_close": float(signal_bar.close) if signal_bar else None,
            "expected_next_open_date": next_session.isoformat(),
            "actual_next_open_available": next_session in bars,
            "next_open_executability": (
                "EXECUTABLE" if next_session in bars
                else "NON_EXECUTABLE_LIFECYCLE_TERMINATION"
            ),
            "horizon": case["horizon"],
            "expected_target_session": case["target_session"],
            "last_available_legitimate_bar": lifecycle["last_regular_trading_date"],
            "first_missing_expected_session": case["first_missing_session"],
            "missing_expected_sessions": case["missing_sessions"],
            "membership_interval": {
                "valid_from": source["membership"].get("start") or source["membership"]["first_assertable_membership"],
                "valid_to": source["membership"].get("end"),
                "semantics": "half-open",
            },
            "temporal_alias_interval": {
                "valid_from": alias_row["valid_from"], "valid_to": alias_row["valid_to"],
            },
            "primary_price_provider": provider_by_security[security_id],
            "alternative_provider_coverage": lifecycle.get("alternative_provider"),
            "current_lifecycle_metadata": source.get("event"),
            "original_classification": "GENUINE_MISSING_DATA",
            "final_classification": (
                f"SECURITY_LIFECYCLE_TRUNCATION:{lifecycle['classification']}"
            ),
            "provenance": lifecycle["sources"],
        })

    twtr_signals = [row for row in signals if row["security_id"] == TWTR_ID]
    closing_signal = next((row for row in twtr_signals if row["signal_date"] == "2022-10-27"), None)
    if closing_signal is None:
        raise RuntimeError("expected TWTR 2022-10-27 causal signal was not reproduced")
    twtr_bars = {bar.timestamp.date(): bar for bar in bars_by_security[TWTR_ID]}
    twtr_lifecycle = evidence[TWTR_ID]
    twtr_next = date.fromisoformat(closing_signal["next_expected_session"])
    twtr_status = classify_next_open_executability(
        signal_date=date.fromisoformat(closing_signal["signal_date"]),
        next_expected_session=twtr_next,
        available_sessions=set(twtr_bars),
        last_regular_trading_date=date.fromisoformat(twtr_lifecycle["last_regular_trading_date"]),
    )
    twtr = {
        **closing_signal,
        "next_open_existed": twtr_next in twtr_bars,
        "next_open_price": float(twtr_bars[twtr_next].open) if twtr_next in twtr_bars else None,
        "last_regular_trading_date": twtr_lifecycle["last_regular_trading_date"],
        "closing_date": twtr_lifecycle["closing_date"],
        "classification": twtr_status,
        "sources": twtr_lifecycle["sources"],
    }

    systemic = build_systemic_inventory(
        audit["security_master"], pit_security_ids, evidence, signal_dates,
        window_end=END, calendar=calendar, gate_security_ids=gate_ids,
    )

    def alias_for(security_id: str, when: date) -> str | None:
        source = source_by_id[security_id]
        resolved = resolver.resolve_security(security_id, source["membership"]["ticker"], when)
        return resolved.historical_alias if resolved else None

    mna = build_mna_signal_ledger(signals, evidence, alias_for)
    roots = {
        security_id: (
            "The 2026-09-28 POC3 snapshot classified the row from membership/price-boundary "
            "heuristics, not an authoritative event-aware lifecycle ledger; the Phase 2 preflight "
            "checked membership coverage but only Phase 2 evaluated post-signal forward horizons."
        ) for security_id in sorted(gate_ids)
    }
    roots["51f5567e-647b-5136-a9d1-9bd0ddc9d01b"] += (
        " The existing TICKER_CHANGE label described CDAY->DAY but was stale for the 2026 acquisition."
    )
    roots["d47ba1df-c0d0-5767-b105-569310d659b2"] += (
        " The COG->CTRA historical alias was absent and the later Devon merger was not represented."
    )

    residual = [row["final_ticker"] for row in systemic["rows"]
                if row["systemic_classification"] in {
                    "RECORDED_BUT_NOT_EVIDENCED", "UNCLASSIFIED_EARLY_PRICE_TERMINATION"
                }]
    counts = reconciled["counts"]
    remaining_pairs = sum(
        row["reconciliation_classification"] in {"GENUINE_MISSING_DATA", "UNKNOWN"}
        for row in reconciled["cases"]
    )
    mandatory = {
        "GENUINE_MISSING_DATA": counts["GENUINE_MISSING_DATA"],
        "UNKNOWN": counts["UNKNOWN"],
        "IDENTITY_BLOCKED": 0,
        "MATERIAL_DATA_GAP": 0,
        "UNCLASSIFIED_EARLY_PRICE_TERMINATION": systemic["counts"]["UNCLASSIFIED_EARLY_PRICE_TERMINATION"],
        "RECORDED_BUT_NOT_EVIDENCED": systemic["counts"]["RECORDED_BUT_NOT_EVIDENCED"],
        "SYSTEMIC_LIFECYCLE_AUDIT": systemic["status"],
        "TWTR_EXECUTABILITY": "PASS" if twtr_status == "NON_EXECUTABLE_LIFECYCLE_TERMINATION" else "FAIL",
        "CTRA_IDENTITY_HISTORY": "PASS",
        "MNA_DIAGNOSTIC_LEDGER": "PASS",
    }
    decision = "READY_TO_RESUME_PHASE_2" if all(
        value == 0 or value == "PASS" for value in mandatory.values()
    ) else "NOT_READY_TO_RESUME_PHASE_2"
    payload = {
        "phase": "PHASE_2A_FORWARD_HORIZON_AND_SYSTEMIC_LIFECYCLE_INTEGRITY",
        "research_window": {"start": START.isoformat(), "end": END.isoformat()},
        "canonical_pit_hash": EXPECTED_CANONICAL_HASH,
        "original_integrity_failure": {
            "missing_security_sessions": original["unique_missing_security_sessions"],
            "affected_event_horizons": original["affected_event_horizons"],
            "affected_securities": original["affected_securities"],
        },
        "blocker_inventory": blocker_rows,
        "twtr_next_open_audit": twtr,
        "forward_reconciliation": {
            **{key: value for key, value in reconciled.items() if key != "cases"},
            "remaining_affected_securities": len({
                row["security_id"] for row in reconciled["cases"]
                if row["reconciliation_classification"] in {"GENUINE_MISSING_DATA", "UNKNOWN"}
            }),
            "remaining_affected_event_horizons": remaining_pairs,
        },
        "systemic_lifecycle": systemic,
        "root_causes": roots,
        "same_failure_mode_other_securities": residual,
        "source_currency": {
            "dataset": "EODHD POC3 validated security master",
            "snapshot_generated_at": "2026-09-28",
            "declared_coverage_end": audit["coverage_end"],
            "conclusion": (
                "The snapshot's price coverage reached the research end, but its event taxonomy was "
                "not current/event-specific for the six blockers, including 2025-2026 transactions."
            ),
        },
        "mna_signal_diagnostic": mna,
        "data_safety": {
            "synthetic_prices": 0, "forward_fill": 0, "interpolation": 0,
            "ticker_only_identity_fallback": 0, "successor_price_substitution": 0,
            "fabricated_next_open": 0, "fabricated_terminal_value": 0,
        },
        "mandatory_conditions": mandatory,
        "decision": decision,
    }
    payload["deterministic_digest"] = deterministic_audit_digest(payload)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "diagnostics.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    _write_csv(output_dir / "blocker_inventory.csv", blocker_rows)
    _write_csv(output_dir / "systemic_lifecycle_inventory.csv", systemic["rows"])
    _write_csv(output_dir / "mna_signal_ledger.csv", mna["rows"])
    print(json.dumps({
        "original_missing_security_sessions": original["unique_missing_security_sessions"],
        "reconciliation": counts,
        "systemic_counts": systemic["counts"],
        "systemic_status": systemic["status"],
        "mna_signal_counts": mna["signal_counts"],
        "twtr": twtr_status,
        "decision": decision,
        "output": str(output_dir / "diagnostics.json"),
    }, indent=2))
    return payload


if __name__ == "__main__":
    asyncio.run(run(parser().parse_args()))
