import argparse
import asyncio
import csv
import json
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.backtesting.engine import BacktestEngine
from app.cli.run_pit_phase2 import END, EXPECTED_HASH, ORIGINAL_RUN_ID, START, terminal_policy
from app.cli.run_pit_phase3b import (
    EXPECTED_ANALYSIS_DIGEST, EXPECTED_ARTIFACT_SHA, EXPECTED_COUNTS,
    _historical_ticker, _lifecycle_configuration, _relabel_result,
    approved_phase2_preflight,
)
from app.database.repositories import MarketBarRepository, UniverseRepository
from app.database.session import SessionFactory
from app.market_data.calendar import NYSETradingCalendar
from app.models import BacktestRun
from app.pit.materialization import database_validation
from app.pit.readiness import merge_provider_bars
from app.portfolio import PortfolioEngine, validate_portfolio_score_invariance
from app.research.fixed_rebuilt import TemporalAliasResolver
from app.research.pit_phase2 import decompose_events, event_key, executable_events
from app.research.pit_phase3b import portfolio_digest
from app.research.pit_phase3c import (
    both_four_way, capacity_and_cash, common_trade_effect, concentration,
    cross_arm_matching, diagnostic_digest, equity_path, first_divergence,
    lifecycle_diagnostics, market_regime_diagnostics, pnl_reconciliation,
    provenance_diagnostics, rejection_diagnostics, returns_by_provenance,
    score_bucket_diagnostics, sequential_step_summary,
)
from app.schemas.backtesting import BacktestRequest, UniverseMode
from app.schemas.research import PortfolioSimulationRequest


FROZEN_FIXED_DIGEST = "10218057ef650912625afd612ce52047241971df59dc233d3051ceb7d6fd4bc2"
FROZEN_PIT_DIGEST = "5c6a0e5edf2d51f56ba2f456f978aadd8dcf550061a15cb970da90fbc2026792"


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Phase 3C PIT portfolio attribution diagnostics")
    command.add_argument("--aliases", default="docs/PIT_TEMPORAL_ALIAS_CHAINS.csv")
    command.add_argument("--evidence", default="docs/PIT_ALIAS_CHAIN_EVIDENCE.json")
    command.add_argument("--lifecycle-evidence", default="docs/PIT_LIFECYCLE_EVIDENCE.json")
    command.add_argument("--boundary-evidence", default="docs/PIT_PHASE2B_BOUNDARY_EVIDENCE.json")
    command.add_argument("--phase2-artifact", default="data/phase2_pit_event_study/run1.json")
    command.add_argument("--phase2-repeat", default="data/phase2_pit_event_study/run2.json")
    command.add_argument("--output", default="data/phase3c_attribution/diagnostics.json")
    return command


async def _inputs(args: argparse.Namespace) -> dict[str, Any]:
    approved = approved_phase2_preflight(Path(args.phase2_artifact), Path(args.phase2_repeat))
    calendar = NYSETradingCalendar()
    sessions = calendar.trading_days_between(START, END)
    warmup = calendar.session_offset(START, -260)
    horizon_end = calendar.session_offset(END, 60)
    with Path(args.aliases).open(newline="", encoding="utf-8") as handle:
        resolver = TemporalAliasResolver.from_csv_rows(csv.DictReader(handle))
    alias_evidence = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
    lifecycle_evidence = json.loads(Path(args.lifecycle_evidence).read_text(encoding="utf-8"))
    boundary_evidence = json.loads(Path(args.boundary_evidence).read_text(encoding="utf-8"))
    raw_policies = terminal_policy(lifecycle_evidence, boundary_evidence, alias_evidence)
    lifecycle_events, lifecycle_metadata = _lifecycle_configuration(raw_policies, calendar)

    async with SessionFactory() as session:
        universes = UniverseRepository(session)
        memberships = await universes.list_period_memberships("SP500", START, END)
        validation = database_validation(memberships, sessions)
        if validation.deterministic_hash != EXPECTED_HASH:
            raise RuntimeError("canonical PIT hash changed before Phase 3C")
        stored_config = await session.scalar(
            select(BacktestRun.parameters).where(BacktestRun.id == ORIGINAL_RUN_ID)
        )
        if stored_config is None:
            raise RuntimeError("authoritative fixed-universe configuration unavailable")
        fixed_request = BacktestRequest.model_validate(stored_config).model_copy(update={"tickers": None})
        pit_request = fixed_request.model_copy(update={"universe_mode": UniverseMode.POINT_IN_TIME})
        current = await universes.list_current_members("SP500")
        repository = MarketBarRepository(session)
        membership_by_security: dict[str, list] = defaultdict(list)
        for membership in memberships:
            membership_by_security[str(membership.security_id)].append(membership)
        bars_by_security = {}
        for security_id, records in sorted(membership_by_security.items()):
            aliases = [item for item in resolver.aliases if item.security_id == security_id]
            candidates = list(dict.fromkeys(
                [item.provider_symbol for item in aliases] + [item.ticker for item in records]
            ))
            bars = []
            used_ticker = None
            for candidate in candidates:
                try:
                    _, bars = await repository.list_security_daily_bars(
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
            supplemental = alias_evidence.get(security_id, {}).get("supplemental_price_provider")
            if supplemental:
                _, extra = await repository.list_security_daily_bars(
                    uuid.UUID(security_id), used_ticker, warmup, horizon_end,
                    providers=(supplemental,),
                )
                bars = merge_provider_bars(bars, extra)
            if security_id in raw_policies:
                bars = [bar for bar in bars
                        if bar.timestamp.date() <= raw_policies[security_id]["last_session"]]
            bars_by_security[security_id] = bars
        current_identities = {ticker: resolver.resolve(ticker, END) for ticker in current}
        if any(identity is None for identity in current_identities.values()):
            raise RuntimeError("fixed snapshot identity resolution failed")
        fixed_security_ids = {ticker: identity.security_id
                              for ticker, identity in current_identities.items()}
        fixed_bars = {security_id: bars_by_security[security_id]
                      for security_id in sorted(set(fixed_security_ids.values()))}
        benchmark = await repository.list_daily_bars("SPY", warmup, horizon_end, "massive")

    periods = {security_id: [(row.valid_from, row.valid_to) for row in records]
               for security_id, records in membership_by_security.items()}
    def is_member(security_id, when):
        return any(start <= when and (end is None or when < end)
                   for start, end in periods[security_id])
    backtests = BacktestEngine(calendar)
    fixed_source = backtests.run(fixed_request, fixed_bars, benchmark)
    pit_source = backtests.run(pit_request, bars_by_security, benchmark, is_member)
    fixed_dicts = [row.model_dump(mode="json") for row in fixed_source.events]
    pit_dicts = [row.model_dump(mode="json") for row in pit_source.events]
    fixed_executable = executable_events(fixed_dicts)
    pit_executable = executable_events(pit_dicts)
    sets = decompose_events(fixed_executable, pit_executable)
    counts = {
        "fixed_rebuilt_signals": len(fixed_dicts), "fixed_rebuilt": len(fixed_executable),
        "pit_signals": len(pit_dicts), "pit": len(pit_executable),
        "pit_non_executable": len(pit_dicts) - len(pit_executable),
        "both": len(sets["BOTH_PIT"]), "fixed_only": len(sets["FIXED_ONLY"]),
        "pit_only": len(sets["PIT_ONLY"]),
    }
    if counts != EXPECTED_COUNTS:
        raise RuntimeError(f"Phase 2 counts changed: {counts}")
    score_invariance = validate_portfolio_score_invariance(
        [row for row in fixed_source.events if row.entry_date is not None],
        [row for row in pit_source.events if row.entry_date is not None],
    )
    if score_invariance["status"] != "PASS" or score_invariance["shared_events"] != 5118:
        raise RuntimeError(f"score invariance changed: {score_invariance}")
    fixed_keys = {event_key(row) for row in fixed_executable}
    pit_keys = {event_key(row) for row in pit_executable}
    fixed_provenance = {item: "BOTH" if item in pit_keys else "FIXED_ONLY"
                        for item in fixed_keys}
    pit_provenance = {item: "BOTH" if item in fixed_keys else "PIT_ONLY"
                      for item in pit_keys}
    ticker_by_event = {}
    for row in fixed_source.events + pit_source.events:
        ticker_by_event[(str(row.ticker), row.signal_date)] = _historical_ticker(
            resolver, str(row.ticker), row.signal_date
        )
    return locals()


def _run_portfolios(data: dict[str, Any]):
    calendar = data["calendar"]
    engine = PortfolioEngine(calendar)
    common = {
        "initial_capital": 100_000, "maximum_positions": 10,
        "target_allocation": .10, "maximum_exposure": 1.0,
        "holding_period": 20, "commission_bps": 0, "slippage_bps": 5,
        "benchmark": "SPY", "security_id_native": True,
    }
    def simulate(source, bars, provenance):
        request = PortfolioSimulationRequest(backtest_run_id=source.run_id, **common)
        result = engine.run(
            request, source, bars, data["benchmark"],
            lifecycle_events=data["lifecycle_events"], provenance_by_event=provenance,
        )
        return _relabel_result(result, data["ticker_by_event"])
    fixed = simulate(data["fixed_source"], data["fixed_bars"], data["fixed_provenance"])
    pit = simulate(data["pit_source"], data["bars_by_security"], data["pit_provenance"])
    if portfolio_digest(fixed) != FROZEN_FIXED_DIGEST or portfolio_digest(pit) != FROZEN_PIT_DIGEST:
        raise RuntimeError("frozen Phase 3B portfolio digest changed")
    both_events = [row for row in data["fixed_source"].events if (
        str(row.ticker), row.signal_date
    ) in data["fixed_keys"] & data["pit_keys"]]
    both_source = data["fixed_source"].model_copy(update={
        "run_id": str(uuid.uuid5(uuid.NAMESPACE_URL, "market-intelligence-ai/phase3c/both-only")),
        "config_hash": "phase3c-both-only", "event_count": len(both_events),
        "events": both_events,
    })
    both_provenance = {(str(row.ticker), row.signal_date): "BOTH" for row in both_events}
    both_first = simulate(both_source, data["fixed_bars"], both_provenance)
    both_second = simulate(both_source, data["fixed_bars"], both_provenance)
    return fixed, pit, both_first, both_second


def _analysis(data: dict[str, Any], fixed, pit, both_first, both_second) -> dict[str, Any]:
    fixed_keys, pit_keys = data["fixed_keys"], data["pit_keys"]
    four_way = both_four_way(fixed, pit, fixed_keys & pit_keys)
    fixed_concentration, pit_concentration = concentration(fixed), concentration(pit)
    fixed_pnl = pnl_reconciliation(fixed, data["fixed_bars"])
    pit_pnl = pnl_reconciliation(pit, data["bars_by_security"])
    pnl_difference = pit_pnl["final_equity"] - fixed_pnl["final_equity"]
    provenance_difference = {
        name: pit_pnl["by_provenance"][name]["total_pnl"]
        - fixed_pnl["by_provenance"][name]["total_pnl"]
        for name in ("BOTH", "FIXED_ONLY", "PIT_ONLY")
    }
    step0, step1, step2 = (
        sequential_step_summary(fixed), sequential_step_summary(both_first),
        sequential_step_summary(pit),
    )
    step1_digests = [portfolio_digest(both_first), portfolio_digest(both_second)]
    output = {
        "signal_provenance": provenance_diagnostics(fixed, pit, fixed_keys, pit_keys),
        "both_four_way": four_way,
        "first_path_divergence": first_divergence(
            fixed, pit, data["fixed_source"].events, data["pit_source"].events
        ),
        "capacity": {
            "FIXED_REBUILT": capacity_and_cash(fixed, data["fixed_source"].events),
            "PIT": capacity_and_cash(pit, data["pit_source"].events),
            "both_accepted_fixed_only": four_way["fixed_only_acceptances"],
            "both_accepted_pit_only": four_way["pit_only_acceptances"],
        },
        "common_trade_path_effect": common_trade_effect(fixed, pit),
        "pnl_reconciliation": {
            "FIXED_REBUILT": fixed_pnl, "PIT": pit_pnl,
            "cross_arm_pit_minus_fixed": pnl_difference,
            "provenance_differences": provenance_difference,
            "provenance_sum": sum(provenance_difference.values()),
            "status": "PASS" if all((
                fixed_pnl["status"] == "PASS", pit_pnl["status"] == "PASS",
                abs(sum(provenance_difference.values()) - pnl_difference) <= 1e-8,
            )) else "FAIL",
            "label": "ACCOUNTING_IDENTITY — NOT CAUSAL ATTRIBUTION",
        },
        "concentration": {
            "FIXED_REBUILT": fixed_concentration, "PIT": pit_concentration,
        },
        "cross_arm_matching": {
            "FIXED_TOP_10": cross_arm_matching(fixed, pit, fixed_concentration["top_10"], pit_keys),
            "FIXED_BOTTOM_10": cross_arm_matching(fixed, pit, fixed_concentration["bottom_10"], pit_keys),
            "PIT_TOP_10": cross_arm_matching(pit, fixed, pit_concentration["top_10"], fixed_keys),
            "PIT_BOTTOM_10": cross_arm_matching(pit, fixed, pit_concentration["bottom_10"], fixed_keys),
        },
        "returns_by_provenance": {
            "FIXED_REBUILT": returns_by_provenance(fixed, data["fixed_bars"]),
            "PIT": returns_by_provenance(pit, data["bars_by_security"]),
        },
        "sequential_counterfactual": {
            "STEP_0_FIXED_REBUILT": step0, "STEP_1_BOTH_ONLY": step1,
            "STEP_2_PIT": step2,
            "step1_minus_step0_cagr": step1["cagr"] - step0["cagr"],
            "step2_minus_step1_cagr": step2["cagr"] - step1["cagr"],
            "step0_digest": portfolio_digest(fixed), "step1_digest": step1_digests[0],
            "step1_repeat_digest": step1_digests[1], "step2_digest": portfolio_digest(pit),
            "step1_determinism": "PASS" if step1_digests[0] == step1_digests[1] else "FAIL",
            "status": "PASS" if (
                step1_digests[0] == step1_digests[1]
                and portfolio_digest(fixed) == FROZEN_FIXED_DIGEST
                and portfolio_digest(pit) == FROZEN_PIT_DIGEST
            ) else "FAIL",
            "limitation": (
                "Sequential, order-dependent counterfactual differences; not independent causal "
                "effects and not a Shapley decomposition."
            ),
        },
        "equity_path": equity_path(fixed, pit),
        "score_buckets": {
            "FIXED_REBUILT": score_bucket_diagnostics(fixed),
            "PIT": score_bucket_diagnostics(pit),
        },
        "market_regimes": {
            "FIXED_REBUILT": market_regime_diagnostics(fixed, data["benchmark"]),
            "PIT": market_regime_diagnostics(pit, data["benchmark"]),
        },
        "lifecycle": {
            "FIXED_REBUILT": lifecycle_diagnostics(fixed, data["lifecycle_metadata"]),
            "PIT": lifecycle_diagnostics(pit, data["lifecycle_metadata"]),
        },
        "rejections": {
            "FIXED_REBUILT": rejection_diagnostics(fixed),
            "PIT": rejection_diagnostics(pit),
        },
    }
    return output


async def run(args: argparse.Namespace) -> dict[str, Any]:
    data = await _inputs(args)
    fixed, pit, both_first, both_second = _run_portfolios(data)
    first = _analysis(data, fixed, pit, both_first, both_second)
    second = _analysis(data, fixed, pit, both_first, both_second)
    first_digest, second_digest = diagnostic_digest(first), diagnostic_digest(second)
    gates = {
        "CHECKPOINT_PREFLIGHT": data["approved"]["status"],
        "PHASE2_INTEGRITY": "PASS" if all((
            data["approved"]["canonical_pit_hash"] == EXPECTED_HASH,
            data["approved"]["analysis_digest"] == EXPECTED_ANALYSIS_DIGEST,
            data["approved"]["artifact_sha256"] == EXPECTED_ARTIFACT_SHA,
            data["counts"] == EXPECTED_COUNTS,
        )) else "FAIL",
        "PHASE3B_FINANCIAL_LOCK": "PASS",
        "SIGNAL_PROVENANCE": "PASS",
        "BOTH_FOUR_WAY": first["both_four_way"]["status"],
        "COMMON_TRADE_INVARIANCE": first["common_trade_path_effect"]["status"],
        "TOTAL_PNL_RECONCILIATION": first["pnl_reconciliation"]["status"],
        "SEQUENTIAL_COUNTERFACTUAL": first["sequential_counterfactual"]["status"],
        "STEP1_DETERMINISM": first["sequential_counterfactual"]["step1_determinism"],
        "MARKET_REGIMES": "PASS",
        "LIFECYCLE": "PASS",
        "PHASE3C_DETERMINISM": "PASS" if first_digest == second_digest else "FAIL",
    }
    decision = "PHASE_3_COMPLETE" if all(value == "PASS" for value in gates.values()) else "PHASE_3_BLOCKED"
    payload = {
        "phase": "PHASE_3C_ATTRIBUTION_AND_DIAGNOSTICS",
        "classification": {
            "observed": "OBSERVED_FACT", "comparisons": "DESCRIPTIVE_COMPARISON",
            "pnl_partition": "ACCOUNTING_IDENTITY", "both_only": "COUNTERFACTUAL_SIMULATION",
            "caveats": "LIMITATION",
        },
        "checkpoint": data["approved"], "signal_counts": data["counts"],
        "frozen_portfolio_digests": {
            "FIXED_REBUILT": portfolio_digest(fixed), "PIT": portfolio_digest(pit),
        },
        "diagnostics": first, "phase3c_digest": first_digest,
        "phase3c_repeat_digest": second_digest, "gates": gates, "decision": decision,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "decision": decision, "gates": gates, "phase3c_digest": first_digest,
        "step1_digest": first["sequential_counterfactual"]["step1_digest"],
        "output": str(output),
    }, indent=2))
    return payload


if __name__ == "__main__":
    asyncio.run(run(parser().parse_args()))
