import argparse
import asyncio
import csv
import hashlib
import importlib.util
import json
import uuid
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.backtesting.engine import BacktestEngine
from app.cli.run_pit_phase2 import END, EXPECTED_HASH, ORIGINAL_RUN_ID, START, terminal_policy
from app.database.repositories import BacktestRepository, MarketBarRepository, UniverseRepository
from app.database.session import SessionFactory
from app.market_data.calendar import NYSETradingCalendar
from app.models import BacktestRun
from app.pit.materialization import database_validation
from app.pit.readiness import merge_provider_bars
from app.portfolio import (
    PortfolioEngine, PortfolioLifecycleEvent, portfolio_candidate_order,
    validate_portfolio_score_invariance,
)
from app.research.fixed_rebuilt import TemporalAliasResolver
from app.research.pit_phase2 import decompose_events, event_key, executable_events
from app.research.pit_phase3b import (
    baseline_engine_equivalence, portfolio_digest, portfolio_summary,
)
from app.schemas.backtesting import BacktestRequest, UniverseMode
from app.schemas.research import PortfolioSimulationRequest, PortfolioSimulationResult


EXPECTED_ANALYSIS_DIGEST = "ed33baca754eb93a6cbe6c898037e9eb8c5734f2762aeb3d8f3d821fdf5cf814"
EXPECTED_ARTIFACT_SHA = "e86c01a3f90573b628d4b9f5096515df80eeeab09684d98f00056d6512084bfc"
EXPECTED_COUNTS = {
    "fixed_rebuilt_signals": 5896, "fixed_rebuilt": 5896,
    "pit_signals": 5398, "pit": 5395, "pit_non_executable": 3,
    "both": 5118, "fixed_only": 778, "pit_only": 277,
}
REQUIRED_PHASE2_GATES = (
    "PIT_DATA_INTEGRITY", "BOTH_INVARIANCE", "PIT_EVENT_DETERMINISM",
    "ARITHMETIC_BRIDGE", "DATE_CLUSTERED_BOOTSTRAP",
)


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(
        description="Phase 3B primary FIXED_REBUILT versus PIT portfolio comparison"
    )
    command.add_argument("--aliases", default="docs/PIT_TEMPORAL_ALIAS_CHAINS.csv")
    command.add_argument("--evidence", default="docs/PIT_ALIAS_CHAIN_EVIDENCE.json")
    command.add_argument("--lifecycle-evidence", default="docs/PIT_LIFECYCLE_EVIDENCE.json")
    command.add_argument("--boundary-evidence", default="docs/PIT_PHASE2B_BOUNDARY_EVIDENCE.json")
    command.add_argument("--phase2-artifact", default="data/phase2_pit_event_study/run1.json")
    command.add_argument("--phase2-repeat", default="data/phase2_pit_event_study/run2.json")
    command.add_argument("--output", default="data/phase3b_portfolio/diagnostics.json")
    command.add_argument("--baseline-engine-source")
    return command


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def approved_phase2_preflight(path: Path, repeat_path: Path) -> dict[str, Any]:
    artifact = json.loads(path.read_text(encoding="utf-8"))
    repeat = json.loads(repeat_path.read_text(encoding="utf-8"))
    gates = {name: artifact["mandatory_conditions"].get(name) for name in REQUIRED_PHASE2_GATES}
    counts = artifact["event_counts"]
    selected_counts = {name: counts.get(name) for name in EXPECTED_COUNTS}
    checks = {
        "canonical_pit_hash": artifact["pit_data_integrity"]["canonical_hash"],
        "analysis_digest": artifact["analysis_digest"],
        "artifact_sha256": _file_sha(path),
        "repeat_artifact_sha256": _file_sha(repeat_path),
        "signal_counts": selected_counts,
        "gates": gates,
    }
    checks["status"] = "PASS" if all((
        checks["canonical_pit_hash"] == EXPECTED_HASH,
        checks["analysis_digest"] == EXPECTED_ANALYSIS_DIGEST,
        checks["artifact_sha256"] == EXPECTED_ARTIFACT_SHA,
        checks["repeat_artifact_sha256"] == EXPECTED_ARTIFACT_SHA,
        repeat.get("analysis_digest") == EXPECTED_ANALYSIS_DIGEST,
        selected_counts == EXPECTED_COUNTS,
        all(value == "PASS" for value in gates.values()),
    )) else "FAIL"
    if checks["status"] != "PASS":
        raise RuntimeError(f"Phase 3B checkpoint preflight failed: {checks}")
    return checks


def _historical_ticker(
    resolver: TemporalAliasResolver, security_id: str, session: date,
) -> str:
    identity = resolver.resolve_security(
        security_id, security_id, session, extend_outer_bounds=True
    )
    if identity is None:
        raise ValueError(
            f"no unique historical ticker for security_id={security_id} session={session}"
        )
    return identity.historical_alias


def _relabel_result(
    result: PortfolioSimulationResult,
    ticker_by_event: dict[tuple[str, date], str],
) -> PortfolioSimulationResult:
    def label(row):
        security_id = str(row.security_id)
        ticker = ticker_by_event[(security_id, row.signal_date)]
        return row.model_copy(update={"ticker": ticker})

    return result.model_copy(update={
        "entries": [label(row) for row in result.entries],
        "trades": [label(row) for row in result.trades],
        "skipped_signals": [label(row) for row in result.skipped_signals],
    })


def _lifecycle_configuration(
    raw: dict[str, dict[str, Any]], calendar: NYSETradingCalendar,
) -> tuple[list[PortfolioLifecycleEvent], dict[str, dict[str, Any]]]:
    events = []
    metadata = {}
    for security_id, policy in sorted(raw.items()):
        if policy["reason"] not in {
            "ACQUISITION", "MERGER", "DELISTING_OTHER", "BANKRUPTCY"
        }:
            continue
        lifecycle_date = (
            date.fromisoformat(policy["closing_date"])
            if policy.get("closing_date")
            else calendar.session_offset(policy["last_session"], 1)
        )
        last_close = None if policy["reason"] == "BANKRUPTCY" else policy["last_session"]
        events.append(PortfolioLifecycleEvent(
            security_id=security_id, reason=policy["reason"],
            exit_session=lifecycle_date,
            last_legitimate_close_session=last_close,
        ))
        metadata[security_id] = {
            "category": policy["reason"],
            "lifecycle_date": lifecycle_date.isoformat(),
            "last_legitimate_close_date": last_close.isoformat() if last_close else None,
        }
    return events, metadata


def _difference(pit: dict[str, Any], fixed: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    return {
        field: (pit[field] - fixed[field]
                if pit.get(field) is not None and fixed.get(field) is not None else None)
        for field in fields
    }


def _load_baseline_engine(path: str):
    spec = importlib.util.spec_from_file_location("phase3a_frozen_portfolio_engine", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load frozen baseline engine: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ordered_candidates(events, sessions: set[date], order_function, policy):
    grouped: dict[date, list] = defaultdict(list)
    for event in events:
        if event.entry_date in sessions:
            grouped[event.entry_date].append(event)
    return [
        (entry_date.isoformat(), str(event.ticker), event.signal_date.isoformat(), event.score)
        for entry_date in sorted(grouped)
        for event in sorted(
            grouped[entry_date],
            key=lambda row: order_function(row, str(row.ticker), policy),
        )
    ]


async def run(args: argparse.Namespace) -> dict[str, Any]:
    approved = approved_phase2_preflight(
        Path(args.phase2_artifact), Path(args.phase2_repeat)
    )
    calendar = NYSETradingCalendar()
    sessions = calendar.trading_days_between(START, END)
    warmup = calendar.session_offset(START, -260)
    horizon_end = calendar.session_offset(END, 60)
    with Path(args.aliases).open(newline="", encoding="utf-8") as handle:
        resolver = TemporalAliasResolver.from_csv_rows(csv.DictReader(handle))
    alias_evidence = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
    lifecycle_evidence = json.loads(
        Path(args.lifecycle_evidence).read_text(encoding="utf-8")
    )
    boundary_evidence = json.loads(
        Path(args.boundary_evidence).read_text(encoding="utf-8")
    )
    raw_policies = terminal_policy(
        lifecycle_evidence, boundary_evidence, alias_evidence
    )
    lifecycle_events, lifecycle_metadata = _lifecycle_configuration(
        raw_policies, calendar
    )

    async with SessionFactory() as session:
        universes = UniverseRepository(session)
        memberships = await universes.list_period_memberships("SP500", START, END)
        validation = database_validation(memberships, sessions)
        if validation.deterministic_hash != EXPECTED_HASH:
            raise RuntimeError("canonical PIT hash changed before financial execution")
        stored_config = await session.scalar(
            select(BacktestRun.parameters).where(BacktestRun.id == ORIGINAL_RUN_ID)
        )
        if stored_config is None:
            raise RuntimeError("authoritative fixed-universe configuration unavailable")
        fixed_request = BacktestRequest.model_validate(stored_config).model_copy(
            update={"tickers": None}
        )
        pit_request = fixed_request.model_copy(
            update={"universe_mode": UniverseMode.POINT_IN_TIME}
        )
        current = await universes.list_current_members("SP500")
        repository = MarketBarRepository(session)
        membership_by_security: dict[str, list] = defaultdict(list)
        for membership in memberships:
            membership_by_security[str(membership.security_id)].append(membership)
        bars_by_security = {}
        for security_id, records in sorted(membership_by_security.items()):
            aliases = [item for item in resolver.aliases if item.security_id == security_id]
            candidates = list(dict.fromkeys(
                [item.provider_symbol for item in aliases]
                + [item.ticker for item in records]
            ))
            provider = None
            bars = []
            used_ticker = None
            for candidate in candidates:
                try:
                    provider, bars = await repository.list_security_daily_bars(
                        uuid.UUID(security_id), candidate, warmup, horizon_end,
                        providers=("eodhd_adjusted_derived",),
                    )
                except Exception:
                    continue
                if bars:
                    used_ticker = candidate
                    break
            if not bars or used_ticker is None:
                raise RuntimeError(f"identity has no logical bars: {security_id}")
            supplemental = alias_evidence.get(security_id, {}).get(
                "supplemental_price_provider"
            )
            if supplemental:
                _, extra = await repository.list_security_daily_bars(
                    uuid.UUID(security_id), used_ticker, warmup, horizon_end,
                    providers=(supplemental,),
                )
                bars = merge_provider_bars(bars, extra)
            if security_id in raw_policies:
                bars = [
                    bar for bar in bars
                    if bar.timestamp.date() <= raw_policies[security_id]["last_session"]
                ]
            bars_by_security[security_id] = bars
        current_identities = {
            ticker: resolver.resolve(ticker, END) for ticker in current
        }
        if any(identity is None for identity in current_identities.values()):
            raise RuntimeError("fixed snapshot identity resolution failed")
        fixed_security_ids = {
            ticker: identity.security_id for ticker, identity in current_identities.items()
        }
        fixed_bars = {
            security_id: bars_by_security[security_id]
            for security_id in sorted(set(fixed_security_ids.values()))
        }
        benchmark = await repository.list_daily_bars(
            "SPY", warmup, horizon_end, "massive"
        )

    periods = {
        security_id: [(row.valid_from, row.valid_to) for row in records]
        for security_id, records in membership_by_security.items()
    }
    is_member = lambda security_id, when: any(
        start <= when and (end is None or when < end)
        for start, end in periods[security_id]
    )
    backtests = BacktestEngine(calendar)
    fixed_source = backtests.run(fixed_request, fixed_bars, benchmark)
    pit_source = backtests.run(
        pit_request, bars_by_security, benchmark, is_member
    )
    fixed_dicts = [row.model_dump(mode="json") for row in fixed_source.events]
    pit_dicts = [row.model_dump(mode="json") for row in pit_source.events]
    fixed_executable = executable_events(fixed_dicts)
    pit_executable = executable_events(pit_dicts)
    sets = decompose_events(fixed_executable, pit_executable)
    runtime_counts = {
        "fixed_rebuilt_signals": len(fixed_dicts),
        "fixed_rebuilt": len(fixed_executable),
        "pit_signals": len(pit_dicts),
        "pit": len(pit_executable),
        "pit_non_executable": len(pit_dicts) - len(pit_executable),
        "both": len(sets["BOTH_PIT"]),
        "fixed_only": len(sets["FIXED_ONLY"]),
        "pit_only": len(sets["PIT_ONLY"]),
    }
    if runtime_counts != EXPECTED_COUNTS:
        raise RuntimeError(
            f"signal reconciliation changed before financial execution: {runtime_counts}"
        )
    score_invariance = validate_portfolio_score_invariance(
        [row for row in fixed_source.events if row.entry_date is not None],
        [row for row in pit_source.events if row.entry_date is not None],
    )
    if score_invariance["status"] != "PASS" or score_invariance["shared_events"] != 5118:
        raise RuntimeError(f"portfolio score invariant changed: {score_invariance}")

    fixed_keys = {event_key(row) for row in fixed_executable}
    pit_keys = {event_key(row) for row in pit_executable}
    fixed_provenance = {
        key: "BOTH" if key in pit_keys else "FIXED_ONLY" for key in fixed_keys
    }
    pit_provenance = {
        key: "BOTH" if key in fixed_keys else "PIT_ONLY" for key in pit_keys
    }
    ticker_by_event = {}
    for row in fixed_source.events + pit_source.events:
        key = (str(row.ticker), row.signal_date)
        ticker_by_event[key] = _historical_ticker(
            resolver, str(row.ticker), row.signal_date
        )
    portfolio = PortfolioEngine(calendar)
    common = {
        "initial_capital": 100_000, "maximum_positions": 10,
        "target_allocation": .10, "maximum_exposure": 1.0,
        "holding_period": 20, "commission_bps": 0,
        "slippage_bps": 5, "benchmark": "SPY", "security_id_native": True,
    }
    fixed_portfolio_request = PortfolioSimulationRequest(
        backtest_run_id=fixed_source.run_id, **common
    )
    pit_portfolio_request = PortfolioSimulationRequest(
        backtest_run_id=pit_source.run_id, **common
    )

    def simulate(request, source, bars, provenance):
        result = portfolio.run(
            request, source, bars, benchmark,
            lifecycle_events=lifecycle_events,
            provenance_by_event=provenance,
        )
        return _relabel_result(result, ticker_by_event)

    fixed_first = simulate(
        fixed_portfolio_request, fixed_source, fixed_bars, fixed_provenance
    )
    pit_first = simulate(
        pit_portfolio_request, pit_source, bars_by_security, pit_provenance
    )
    fixed_second = simulate(
        fixed_portfolio_request, fixed_source, fixed_bars, fixed_provenance
    )
    pit_second = simulate(
        pit_portfolio_request, pit_source, bars_by_security, pit_provenance
    )
    deterministic = {
        "fixed_first_digest": portfolio_digest(fixed_first),
        "fixed_second_digest": portfolio_digest(fixed_second),
        "pit_first_digest": portfolio_digest(pit_first),
        "pit_second_digest": portfolio_digest(pit_second),
    }
    deterministic["status"] = "PASS" if (
        deterministic["fixed_first_digest"] == deterministic["fixed_second_digest"]
        and deterministic["pit_first_digest"] == deterministic["pit_second_digest"]
    ) else "FAIL"
    if deterministic["status"] != "PASS":
        raise RuntimeError(f"PORTFOLIO_DETERMINISM failed: {deterministic}")

    baseline_equivalence = {"status": "NOT_RUN"}
    if args.baseline_engine_source:
        baseline_module = _load_baseline_engine(args.baseline_engine_source)
        baseline_result = baseline_module.PortfolioEngine(calendar).run(
            fixed_portfolio_request, fixed_source, fixed_bars, benchmark,
            lifecycle_events=lifecycle_events,
            provenance_by_event=fixed_provenance,
        )
        session_set = set(calendar.trading_days_between(START, END))
        baseline_equivalence = baseline_engine_equivalence(
            baseline_result, fixed_first,
            baseline_ordered_candidates=_ordered_candidates(
                fixed_source.events, session_set,
                baseline_module.portfolio_candidate_order,
                fixed_portfolio_request.selection_policy,
            ),
            current_ordered_candidates=_ordered_candidates(
                fixed_source.events, session_set, portfolio_candidate_order,
                fixed_portfolio_request.selection_policy,
            ),
        )
        if baseline_equivalence["status"] != "PASS":
            raise RuntimeError(
                f"BASELINE_ENGINE_EQUIVALENCE failed: {baseline_equivalence}"
            )

    fixed_summary = portfolio_summary(
        fixed_first, expected_executable=EXPECTED_COUNTS["fixed_rebuilt"],
        bars_by_security=fixed_bars,
        lifecycle_by_security=lifecycle_metadata,
    )
    pit_summary = portfolio_summary(
        pit_first, expected_executable=EXPECTED_COUNTS["pit"],
        bars_by_security=bars_by_security,
        lifecycle_by_security=lifecycle_metadata,
    )
    approved_financial_values = {
        "fixed_final_equity": fixed_summary["metrics"]["final_equity"],
        "fixed_total_return": fixed_summary["metrics"]["total_return"],
        "fixed_cagr": fixed_summary["metrics"]["annualized_return_cagr"],
        "fixed_closed_trades": fixed_summary["metrics"]["number_of_trades"],
        "fixed_open_positions": fixed_summary["metrics"]["open_positions_at_end"],
        "fixed_accepted": fixed_summary["signal_outcomes"]["ACCEPTED"],
        "fixed_total_slippage": fixed_summary["metrics"]["total_slippage_dollars"],
        "pit_final_equity": pit_summary["metrics"]["final_equity"],
        "pit_total_return": pit_summary["metrics"]["total_return"],
        "pit_cagr": pit_summary["metrics"]["annualized_return_cagr"],
        "pit_closed_trades": pit_summary["metrics"]["number_of_trades"],
        "pit_open_positions": pit_summary["metrics"]["open_positions_at_end"],
        "pit_accepted": pit_summary["signal_outcomes"]["ACCEPTED"],
        "pit_total_slippage": pit_summary["metrics"]["total_slippage_dollars"],
    }
    approved_financial_status = "PASS" if all((
        round(approved_financial_values["fixed_final_equity"], 2) == 415_428.20,
        round(approved_financial_values["fixed_total_return"] * 100, 4) == 315.4282,
        round(approved_financial_values["fixed_cagr"] * 100, 6) == 33.062544,
        approved_financial_values["fixed_closed_trades"] == 594,
        approved_financial_values["fixed_open_positions"] == 10,
        approved_financial_values["fixed_accepted"] == 604,
        round(approved_financial_values["fixed_total_slippage"], 2) == 12_517.20,
        round(approved_financial_values["pit_final_equity"], 2) == 243_797.07,
        round(approved_financial_values["pit_total_return"] * 100, 4) == 143.7971,
        round(approved_financial_values["pit_cagr"] * 100, 6) == 19.571826,
        approved_financial_values["pit_closed_trades"] == 593,
        approved_financial_values["pit_open_positions"] == 9,
        approved_financial_values["pit_accepted"] == 602,
        round(approved_financial_values["pit_total_slippage"], 2) == 9_377.61,
        deterministic["fixed_first_digest"] ==
            "10218057ef650912625afd612ce52047241971df59dc233d3051ceb7d6fd4bc2",
        deterministic["pit_first_digest"] ==
            "5c6a0e5edf2d51f56ba2f456f978aadd8dcf550061a15cb970da90fbc2026792",
    )) else "FAIL"
    if approved_financial_status != "PASS":
        raise RuntimeError(
            f"approved Phase 3B results did not reproduce: {approved_financial_values}"
        )
    non_executable = [
        row for row in pit_first.skipped_signals
        if row.reason == "NON_EXECUTABLE_LIFECYCLE_TERMINATION"
    ]
    non_executable_ledger = [
        {
            "security_id": row.security_id, "ticker": row.ticker,
            "signal_date": row.signal_date.isoformat(), "reason": row.reason,
            "entered": any(
                entry.security_id == row.security_id
                and entry.signal_date == row.signal_date
                for entry in pit_first.entries
            ),
        }
        for row in non_executable
    ]
    required_nonexec = {"TWTR", "DAY", "HOLX"}
    nonexec_status = "PASS" if (
        len(non_executable_ledger) == 3
        and {row["ticker"] for row in non_executable_ledger} == required_nonexec
        and not any(row["entered"] for row in non_executable_ledger)
    ) else "FAIL"

    twtr_security_id = "ae13e1b5-7a16-59c1-95ce-2bfa52b340d7"
    twtr_trade = next(
        row for row in pit_first.trades
        if row.security_id == twtr_security_id and row.lifecycle_treatment is not None
    )
    twtr_nonexec = next(
        row for row in non_executable
        if row.security_id == twtr_security_id
    )
    twtr_entry = next(
        row for row in pit_first.entries
        if row.security_id == twtr_security_id
        and row.signal_date == twtr_trade.signal_date
    )
    twtr_exit_slippage_expected = twtr_trade.quantity * (
        twtr_trade.reference_exit_price - twtr_trade.exit_price
    )
    twtr_audit = {
        "executed_event": {
            "security_id": twtr_trade.security_id, "ticker": twtr_trade.ticker,
            "signal_date": twtr_trade.signal_date.isoformat(),
            "entry_date": twtr_trade.entry_date.isoformat(),
            "scheduled_exit_date": twtr_entry.scheduled_exit_date.isoformat(),
            "termination_date": lifecycle_metadata[twtr_security_id]["lifecycle_date"],
            "actual_exit_date": twtr_trade.exit_date.isoformat(),
            "classification": twtr_trade.lifecycle_treatment,
            "reference_exit_price": twtr_trade.reference_exit_price,
            "exit_price": twtr_trade.exit_price,
            "exit_slippage": twtr_trade.exit_slippage_cost,
        },
        "non_executable_event": {
            "security_id": twtr_nonexec.security_id, "ticker": twtr_nonexec.ticker,
            "signal_date": twtr_nonexec.signal_date.isoformat(), "entry_date": None,
            "scheduled_exit_date": None,
            "termination_date": lifecycle_metadata[twtr_security_id]["lifecycle_date"],
            "actual_exit_date": None,
            "classification": twtr_nonexec.reason,
        },
        "checks": {
            "distinct_signals": twtr_trade.signal_date != twtr_nonexec.signal_date,
            "executed_had_legitimate_next_open": twtr_trade.entry_date is not None,
            "non_executable_did_not_enter": not any(
                row.security_id == twtr_security_id
                and row.signal_date == twtr_nonexec.signal_date
                for row in pit_first.entries
            ),
            "same_security_last_close": twtr_trade.reference_exit_price == 53.7,
            "exit_slippage_exactly_once": abs(
                twtr_trade.exit_slippage_cost - twtr_exit_slippage_expected
            ) <= 1e-10,
            "consideration_not_substituted": twtr_trade.reference_exit_price != 54.2,
            "no_successor_or_synthetic_price": twtr_trade.lifecycle_treatment ==
                "ACQUISITION_LAST_LEGITIMATE_CLOSE",
        },
    }
    twtr_audit["status"] = "PASS" if all(twtr_audit["checks"].values()) else "FAIL"
    if twtr_audit["status"] != "PASS":
        raise RuntimeError(f"TWTR_LIFECYCLE_AUDIT failed: {twtr_audit}")

    difference_fields = [
        "total_return", "annualized_volatility", "maximum_drawdown",
        "sharpe_ratio", "sortino_ratio", "calmar_ratio", "number_of_trades",
        "positive_trade_rate", "mean_trade_return", "median_trade_return",
        "average_simultaneous_positions", "portfolio_exposure",
        "average_cash_percentage", "total_slippage_dollars",
    ]
    secondary = _difference(
        pit_summary["metrics"], fixed_summary["metrics"], difference_fields
    )
    fixed_cagr = fixed_summary["metrics"]["annualized_return_cagr"]
    pit_cagr = pit_summary["metrics"]["annualized_return_cagr"]
    primary = {
        "fixed_rebuilt_cagr": fixed_cagr, "pit_cagr": pit_cagr,
        "pit_minus_fixed_rebuilt_cagr_percentage_points_per_year": (
            (pit_cagr - fixed_cagr) * 100
        ),
    }
    phase2_difference = -0.006026297883796662
    phase3_difference = pit_cagr - fixed_cagr
    direction = (
        "SAME DIRECTION" if phase2_difference * phase3_difference > 0
        else "DIFFERENT DIRECTION"
    )
    gates = {
        "CHECKPOINT_PREFLIGHT": approved["status"],
        "SIGNAL_RECONCILIATION": "PASS" if runtime_counts == EXPECTED_COUNTS else "FAIL",
        "PORTFOLIO_SCORE_INVARIANT": score_invariance["status"],
        "FIXED_REBUILT_SIGNAL_OUTCOMES": fixed_summary["signal_outcomes"]["status"],
        "PIT_SIGNAL_OUTCOMES": pit_summary["signal_outcomes"]["status"],
        "FIXED_REBUILT_ACCOUNTING": fixed_summary["accounting_reconciliation"]["status"],
        "PIT_ACCOUNTING": pit_summary["accounting_reconciliation"]["status"],
        "ACCOUNTING_RECONCILIATION": "PASS" if all(
            row["accounting_reconciliation"]["status"] == "PASS"
            for row in (fixed_summary, pit_summary)
        ) else "FAIL",
        "SLIPPAGE_RECONCILIATION": "PASS" if all(
            row["slippage_reconciliation"]["status"] == "PASS"
            for row in (fixed_summary, pit_summary)
        ) else "FAIL",
        "OPEN_POSITION_RECONCILIATION": "PASS" if all(
            row["open_positions"]["status"] == "PASS"
            for row in (fixed_summary, pit_summary)
        ) else "FAIL",
        "PORTFOLIO_DETERMINISM": deterministic["status"],
        "NON_EXECUTABLE_SIGNALS": nonexec_status,
        "APPROVED_FINANCIAL_VALUES": approved_financial_status,
        "BASELINE_ENGINE_EQUIVALENCE": baseline_equivalence["status"],
        "TWTR_LIFECYCLE_AUDIT": twtr_audit["status"],
        "REALIZED_PNL_CONCENTRATION": "PASS" if all(
            row["realized_pnl_concentration"]["status"] == "PASS"
            for row in (fixed_summary, pit_summary)
        ) else "FAIL",
    }
    decision = "READY_FOR_PHASE_3C" if all(
        value == "PASS" for value in gates.values()
    ) else "NOT_READY_FOR_PHASE_3C"
    payload = {
        "phase": "PHASE_3B_PRIMARY_PIT_PORTFOLIO_COMPARISON",
        "checkpoint_preflight": approved,
        "runtime_signal_counts": runtime_counts,
        "methodology": common,
        "fixed_rebuilt": fixed_summary,
        "pit": pit_summary,
        "primary_result": primary,
        "secondary_differences_pit_minus_fixed": secondary,
        "non_executable_pit_signals": non_executable_ledger,
        "portfolio_determinism": deterministic,
        "baseline_engine_equivalence": baseline_equivalence,
        "approved_financial_values": {
            "status": approved_financial_status, **approved_financial_values,
        },
        "twtr_lifecycle_audit": twtr_audit,
        "phase2_vs_phase3_direction": {
            "phase2_20d_mean_excess_difference_bp": -60.2630,
            "phase3_cagr_difference_percentage_points_per_year":
                primary["pit_minus_fixed_rebuilt_cagr_percentage_points_per_year"],
            "direction": direction,
        },
        "gates": gates,
        "decision": decision,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "decision": decision, "gates": gates, "primary_result": primary,
        "fixed_digest": deterministic["fixed_first_digest"],
        "pit_digest": deterministic["pit_first_digest"],
        "output": str(output),
    }, indent=2))
    return payload


if __name__ == "__main__":
    asyncio.run(run(parser().parse_args()))
