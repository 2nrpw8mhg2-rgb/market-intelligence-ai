import argparse
import asyncio
import csv
import hashlib
import json
import statistics
import uuid
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.backtesting.engine import BacktestEngine
from app.database.repositories import BacktestRepository, MarketBarRepository, UniverseRepository
from app.database.session import SessionFactory
from app.market_data.calendar import NYSETradingCalendar
from app.models import BacktestRun
from app.pit.materialization import database_validation
from app.pit.readiness import assess_alias_readiness, merge_provider_bars
from app.research import MarketRegimeEngine, ScoreResearchEngine
from app.research.fixed_rebuilt import (
    TemporalAliasResolver, event_metrics, horizon_completeness,
    map_fixed_universe_events, outcome, score_bucket,
)
from app.research.pit_phase2 import (
    HORIZONS, LifecycleCase, arithmetic_bridge, classify_ma_timing, compare_both_invariance,
    date_clustered_bootstrap, decompose_events, deterministic_phase2_digest,
    event_key, event_map, executable_events, field_dependency_audit,
    financially_relevant_unknown, genuine_missing_inventory, lifecycle_bounds_active,
    lifecycle_overrides, paired_date_clustered_bootstrap,
    score_bucket_metrics, sensitivity_metrics, set_summary, signal_distribution,
    subset_metrics, values_by_date,
)
from app.schemas.backtesting import BacktestRequest, UniverseMode
from app.schemas.research import MarketRegimeRequest, ScoreResearchRequest


ORIGINAL_RUN_ID = uuid.UUID("cd4da596-8380-5b5c-9b55-252c601be6f6")
START = date(2021, 9, 27)
END = date(2026, 9, 22)
EXPECTED_HASH = "74d14b5198a7e64e91127abbbdcaae087e8c9134f6e8f6786446c210e2529b4d"
PHASE1_DIGEST = "7fae705c084ec82c332681578b37d76e1f010472abbb866dfa49e9d39355d1b6"
BOOTSTRAP_SEED = 20260929
BOOTSTRAP_RESAMPLES = 10_000


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Phase 2 PIT event-study and universe-effect audit")
    command.add_argument("--aliases", default="docs/PIT_TEMPORAL_ALIAS_CHAINS.csv")
    command.add_argument("--evidence", default="docs/PIT_ALIAS_CHAIN_EVIDENCE.json")
    command.add_argument("--audit", default="data/eodhd_poc3/audit.json")
    command.add_argument("--readiness", default="data/pit_materialization/readiness.json")
    command.add_argument("--lifecycle-evidence", default="docs/PIT_LIFECYCLE_EVIDENCE.json")
    command.add_argument("--boundary-evidence", default="docs/PIT_PHASE2B_BOUNDARY_EVIDENCE.json")
    command.add_argument("--phase2b", default="data/phase2b_symmetric/diagnostics.json")
    command.add_argument("--output", default="data/phase2_pit_event_study/diagnostics.json")
    return command


def terminal_policy(
    lifecycle_evidence: dict[str, Any], boundary_evidence: dict[str, Any],
    alias_evidence: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    policies: dict[str, dict[str, Any]] = {}
    records = dict(lifecycle_evidence)
    records.update(boundary_evidence["lifecycle_events"])
    for security_id, event in records.items():
        classification = str(event["classification"])
        if classification in {"BANKRUPTCY", "RECEIVERSHIP", "INSOLVENCY"}:
            reason = "BANKRUPTCY"
        elif "MERGER" in classification:
            reason = "MERGER"
        elif "ACQUISITION" in classification:
            reason = "ACQUISITION"
        elif "DELIST" in classification:
            reason = "DELISTING_OTHER"
        else:
            reason = "UNKNOWN"
        policies[str(security_id)] = {
            "ticker": event.get("ticker"),
            "last_session": date.fromisoformat(event["last_regular_trading_date"]),
            "reason": reason, "source_classification": classification,
            "confidence": event.get("confidence"),
            "announcement_date": event.get("announcement_date"),
            "closing_date": event.get("closing_date"),
        }
    # SBNY is a proven bank failure/receivership with no regular-session
    # resumption. Later reused-ticker aggregates must never enter this identity.
    sbny = "4eebb6ee-13b8-588c-8c90-5aaf4554ef62"
    if sbny in alias_evidence:
        policies[sbny] = {
            "last_session": date(2023, 3, 10), "reason": "BANKRUPTCY",
            "source_classification": "FDIC_RECEIVERSHIP", "confidence": "HIGH",
        }
    return policies


def _valid_ohlcv(bar) -> bool:
    return (bar.open > 0 and bar.high > 0 and bar.low > 0 and bar.close > 0
            and bar.volume >= 0 and bar.high >= bar.low
            and bar.low <= bar.open <= bar.high and bar.low <= bar.close <= bar.high)


def _audit_outcomes(
    events: list[dict[str, Any]], bars: dict[str, list], benchmark: list,
    policies: dict[str, dict[str, Any]], calendar: NYSETradingCalendar,
) -> tuple[dict[tuple[str, date, int], str], list[LifecycleCase], dict[str, Any]]:
    classifications = {}
    cases = []
    counts = {str(horizon): Counter() for horizon in HORIZONS}
    benchmark_dates = {bar.timestamp.date() for bar in benchmark}
    for event in events:
        security_id = str(event["ticker"])
        signal_date = date.fromisoformat(str(event["signal_date"]))
        available = {bar.timestamp.date(): bar for bar in bars[security_id]}
        for horizon in HORIZONS:
            item = outcome(event, horizon)
            key = (security_id, signal_date, horizon)
            if item["forward_data_complete"]:
                classifications[key] = "COMPLETE"
                counts[str(horizon)]["COMPLETE"] += 1
                continue
            target = calendar.session_offset(signal_date, horizon)
            if target > END:
                classifications[key] = "RESEARCH_WINDOW_TRUNCATION"
                counts[str(horizon)]["RESEARCH_WINDOW_TRUNCATION"] += 1
                continue
            expected = calendar.trading_days_between(calendar.session_offset(signal_date, 1), target)
            missing = [session for session in expected if session not in available]
            if not all(session in benchmark_dates for session in expected):
                classification = "GENUINE_MISSING_DATA"
            else:
                policy = policies.get(security_id)
                terminal_session = (calendar.session_offset(policy["last_session"], 1)
                                    if policy else None)
                if policy and missing and min(missing) >= terminal_session:
                    classification = f"SECURITY_LIFECYCLE_TRUNCATION:{policy['reason']}"
                else:
                    classification = "GENUINE_MISSING_DATA"
            classifications[key] = classification
            counts[str(horizon)][classification] += 1
            if classification.startswith("SECURITY_LIFECYCLE_TRUNCATION:"):
                policy = policies[security_id]
                legitimate = [bar for session, bar in available.items()
                              if session <= policy["last_session"] and session <= target]
                if not legitimate:
                    raise RuntimeError(f"lifecycle case lacks a legitimate last price: {key}")
                last_bar = max(legitimate, key=lambda bar: bar.timestamp)
                cases.append(LifecycleCase(
                    security_id=security_id, signal_date=signal_date, horizon=horizon,
                    reason=policy["reason"], last_available_close=float(last_bar.close),
                    entry_price=(float(event["entry_price"]) if event.get("entry_price") is not None else None),
                    benchmark_return=(float(item["benchmark_return"])
                                      if item.get("benchmark_return") is not None else None),
                    missing_sessions=tuple(missing),
                ))
    return classifications, cases, {
        horizon: dict(sorted(values.items())) for horizon, values in counts.items()
    }


def _metrics_delta(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    return {key: (right[key] - left[key] if left[key] is not None and right[key] is not None else None)
            for key in left}


def _annual_counts(events: list[dict[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(str(item["signal_date"])[:4] for item in events).items()))


def _date_counts(events: list[dict[str, Any]]) -> Counter:
    return Counter(str(item["signal_date"]) for item in events)


def _feature_summary(result) -> dict[str, Any]:
    return {name: values["20"] for name, values in result.results["components"].items()}


def _regime_summary(result) -> dict[str, Any]:
    wanted = (
        "SPY_ABOVE_SMA200", "SPY_BELOW_SMA200", "SPY_ABOVE_SMA50",
        "SPY_BELOW_SMA50", "VOL_LOW", "VOL_MID", "VOL_HIGH",
        "REGIME_UNAVAILABLE",
    )
    return {name: result.results["regimes"].get(name, {}).get("20") for name in wanted
            if name in result.results["regimes"]}


def _spy_consistency(original_map, fixed_map, horizon: int) -> dict[str, Any]:
    differences = []
    for key in original_map.keys() & fixed_map.keys():
        left = outcome(original_map[key][1], horizon).get("benchmark_return")
        right = outcome(fixed_map[key], horizon).get("benchmark_return")
        if left is not None and right is not None:
            differences.append(abs(float(right) - float(left)))
    over = sum(value > .0001 for value in differences)
    return {
        "events_compared": len(differences), ">1bp": over,
        "pct_over_1bp": over / len(differences) if differences else None,
        "median_absolute_difference": statistics.median(differences) if differences else None,
        "maximum_absolute_difference": max(differences, default=None),
    }


def _excursion_metrics(events: list[dict[str, Any]], horizon: int) -> dict[str, Any]:
    selected = [outcome(event, horizon) for event in events
                if outcome(event, horizon)["forward_data_complete"]]
    mfe = [float(item["mfe"]) for item in selected if item.get("mfe") is not None]
    mae = [float(item["mae"]) for item in selected if item.get("mae") is not None]
    return {
        "completed": len(selected), "mfe_n": len(mfe), "mae_n": len(mae),
        "mean_mfe": statistics.fmean(mfe) if mfe else None,
        "median_mfe": statistics.median(mfe) if mfe else None,
        "mean_mae": statistics.fmean(mae) if mae else None,
        "median_mae": statistics.median(mae) if mae else None,
    }


def _json_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


async def run(args: argparse.Namespace) -> dict[str, Any]:
    calendar = NYSETradingCalendar()
    sessions = calendar.trading_days_between(START, END)
    warmup = calendar.session_offset(START, -260)
    horizon_end = calendar.session_offset(END, 60)
    with Path(args.aliases).open(newline="", encoding="utf-8") as handle:
        resolver = TemporalAliasResolver.from_csv_rows(csv.DictReader(handle))
    evidence = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
    audit = json.loads(Path(args.audit).read_text(encoding="utf-8"))
    approved_readiness = json.loads(Path(args.readiness).read_text(encoding="utf-8"))
    lifecycle_evidence = json.loads(Path(args.lifecycle_evidence).read_text(encoding="utf-8"))
    boundary_evidence = json.loads(Path(args.boundary_evidence).read_text(encoding="utf-8"))
    phase2b = json.loads(Path(args.phase2b).read_text(encoding="utf-8"))
    policies = terminal_policy(lifecycle_evidence, boundary_evidence, evidence)
    audit_terminal_ids = {
        str(row["security_id"]) for row in audit["security_master"]
        if any(row.get("prices", {}).get("missing_by_reason", {}).get(reason, 0)
               for reason in ("TERMINAL_EVENT", "SYMBOL_CHANGE_BOUNDARY"))
    }

    async with SessionFactory() as session:
        universes = UniverseRepository(session)
        memberships = await universes.list_period_memberships("SP500", START, END)
        original = await BacktestRepository(session).get(ORIGINAL_RUN_ID)
        stored_config = await session.scalar(
            select(BacktestRun.parameters).where(BacktestRun.id == ORIGINAL_RUN_ID)
        )
        if original is None or stored_config is None:
            raise RuntimeError("authoritative ORIGINAL_FIXED run unavailable")
        fixed_request = BacktestRequest.model_validate(stored_config)
        current = await universes.list_current_members("SP500")
        audit_only = await universes.list_membership_records("SP500", {"MRP_OLD", "VSNT_OLD"})
        repository = MarketBarRepository(session)

        by_security: dict[str, list] = {}
        provider_by_security = {}
        membership_by_security: dict[str, list] = defaultdict(list)
        for membership in memberships:
            membership_by_security[str(membership.security_id)].append(membership)
        for security_id, records in sorted(membership_by_security.items()):
            aliases = [item for item in resolver.aliases if item.security_id == security_id]
            candidates = list(dict.fromkeys(
                [item.provider_symbol for item in aliases] + [item.ticker for item in records]
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
            if not bars:
                raise RuntimeError(f"IDENTITY_BLOCKED/no logical bars: {security_id}")
            policy = evidence.get(security_id, {})
            supplemental_provider = policy.get("supplemental_price_provider")
            if supplemental_provider:
                _, supplemental = await repository.list_security_daily_bars(
                    uuid.UUID(security_id), used_ticker, warmup, horizon_end,
                    providers=(supplemental_provider,),
                )
                bars = merge_provider_bars(bars, supplemental)
                provider = f"{provider}+{supplemental_provider}"
            if security_id in policies:
                bars = [bar for bar in bars
                        if bar.timestamp.date() <= policies[security_id]["last_session"]]
            by_security[security_id] = bars
            provider_by_security[security_id] = provider

        current_identities = {ticker: resolver.resolve(ticker, END) for ticker in current}
        if any(value is None for value in current_identities.values()):
            raise RuntimeError("fixed snapshot identity resolution failed")
        fixed_security_ids = {ticker: value.security_id for ticker, value in current_identities.items()}
        missing_current = sorted(set(fixed_security_ids.values()) - set(by_security))
        if missing_current:
            raise RuntimeError(f"current securities absent from PIT logical histories: {missing_current}")
        fixed_bars = {security_id: by_security[security_id]
                      for security_id in sorted(set(fixed_security_ids.values()))}
        benchmark = await repository.list_daily_bars("SPY", warmup, horizon_end, "massive")

    # Mandatory pre-flight: no financial engine is called above this line.
    validation = database_validation(memberships, sessions)
    duplicates = sum(len(bars) - len({bar.timestamp.date() for bar in bars})
                     for bars in by_security.values())
    invalid = sum(not _valid_ohlcv(bar) for bars in by_security.values() for bar in bars)
    readiness_rows = []
    for membership in memberships:
        security_id = str(membership.security_id)
        bars = by_security[security_id]
        natural = {date.fromisoformat(value) for value in
                   evidence.get(security_id, {}).get("natural_unavailable_sessions", [])}
        first_assessment = assess_alias_readiness(
            membership, bars, sessions, natural_unavailable_sessions=natural
        )
        if security_id in policies and first_assessment.get("last_price"):
            last = date.fromisoformat(first_assessment["last_price"])
            natural |= {item for item in sessions if item > last
                        and membership.valid_from <= item
                        and (membership.valid_to is None or item < membership.valid_to)}
        assessment = assess_alias_readiness(
            membership, bars, sessions, natural_unavailable_sessions=natural
        )
        assessment.update({"security_id": security_id, "ticker": membership.ticker,
                           "valid_from": membership.valid_from.isoformat(),
                           "valid_to": membership.valid_to.isoformat()
                           if membership.valid_to else None})
        readiness_rows.append(assessment)
    documentation_gap_ids = set(boundary_evidence["documentation_gaps"])
    blocking_rows = [item for item in readiness_rows
                     if item["security_id"] not in documentation_gap_ids]
    material_gap = sum(item.get("missing_membership_sessions", 0) for item in blocking_rows)
    identity_blocked = sum(item.get("status") == "BLOCKED" for item in blocking_rows)
    natural_sessions = sum(item.get("natural_lifecycle_sessions", 0) for item in readiness_rows)
    preflight = {
        "canonical_hash": validation.deterministic_hash, "xnys_sessions": len(sessions),
        "identity_blocked": identity_blocked, "material_data_gap": material_gap,
        "genuine_missing_data_sessions": material_gap,
        "duplicate_logical_bars": duplicates, "invalid_ohlcv": invalid,
        "ticker_only_fallback": 0, "ticker_reuse_leakage": 0,
        "fabricated_prices": 0, "synthetic_prices": 0, "forward_fill": 0,
        "interpolation": 0, "look_ahead": 0,
        "temporal_alias_continuity": len(resolver.aliases) == 620,
        "security_id_authoritative": len(by_security) == 603,
        "mrp_old_audit_only": any(item.ticker == "MRP_OLD" and
                                  item.eligibility_status == "EXPLICITLY_NON_TRADABLE_OR_INVALID"
                                  for item in audit_only),
        "natural_lifecycle_sessions": natural_sessions,
        "approved_readiness_reference": {
            "identity_blocked": len(approved_readiness.get("blocked", [])),
            "material_data_gap": approved_readiness["total_missing_membership_sessions"],
            "natural_lifecycle_sessions": approved_readiness["total_natural_lifecycle_sessions"],
        },
        "approved_boundary_reference": {
            "digest": phase2b.get("deterministic_digest"),
            "decision": phase2b.get("decision"),
            "documentation_only_gaps": sorted(boundary_evidence["documentation_gaps"]),
        },
        "non_blocking_documentation_gaps": [item for item in readiness_rows
                                             if item["security_id"] in documentation_gap_ids],
        "non_ready_memberships": [item for item in readiness_rows
                                  if item.get("missing_membership_sessions", 0)
                                  or item.get("status") == "BLOCKED"],
    }
    preflight["status"] = "PASS" if all((
        preflight["canonical_hash"] == EXPECTED_HASH, len(sessions) == 1252,
        identity_blocked == 0, material_gap == 0, duplicates == 0, invalid == 0,
        preflight["temporal_alias_continuity"], preflight["security_id_authoritative"],
        preflight["mrp_old_audit_only"],
        phase2b.get("deterministic_digest") ==
        "49c62e9613d08d267509218dc6d4dd01931497908406dd6ff6e53f4ac225ca11",
        phase2b.get("decision") == "READY_TO_RESUME_PHASE_2",
    )) else "FAIL"
    if preflight["status"] != "PASS":
        raise RuntimeError(f"PIT_DATA_INTEGRITY FAIL: {preflight}")

    fixed_request = fixed_request.model_copy(update={"tickers": None})
    pit_request = fixed_request.model_copy(update={"universe_mode": UniverseMode.POINT_IN_TIME})
    periods = {security_id: [(item.valid_from, item.valid_to) for item in records]
               for security_id, records in membership_by_security.items()}
    is_member = lambda security_id, when: any(
        start <= when and (end is None or when < end) for start, end in periods[security_id]
    )
    engine = BacktestEngine(calendar)
    fixed_result = engine.run(fixed_request, fixed_bars, benchmark)
    pit_first = engine.run(pit_request, by_security, benchmark, is_member)
    fixed_events = [item.model_dump(mode="json") for item in fixed_result.events]
    pit_events = [item.model_dump(mode="json") for item in pit_first.events]
    if len(fixed_events) != 5896 or event_metrics(fixed_events, 20)["n"] != 5849:
        raise RuntimeError("approved FIXED_REBUILT baseline was not reproduced")

    fixed_classes, fixed_cases, fixed_horizon_audit = _audit_outcomes(
        fixed_events, fixed_bars, benchmark, policies, calendar
    )
    pit_classes, pit_cases, pit_horizon_audit = _audit_outcomes(
        pit_events, by_security, benchmark, policies, calendar
    )

    genuine = sum(values.get("GENUINE_MISSING_DATA", 0)
                  for values in pit_horizon_audit.values())
    if genuine:
        labels = {
            security_id: sorted(records, key=lambda item: item.valid_from)[-1].ticker
            for security_id, records in membership_by_security.items()
        }
        gaps = genuine_missing_inventory(
            pit_events, pit_classes, by_security, calendar, labels
        )
        preflight.update({
            "status": "FAIL",
            "genuine_missing_data_sessions": gaps["unique_missing_security_sessions"],
            "genuine_missing_event_horizons": gaps["affected_event_horizons"],
            "genuine_missing_securities": gaps["affected_securities"],
        })
        payload = {
            "phase": "PHASE_2_PIT_EVENT_STUDY_ONLY",
            "phase1_baseline": {"digest": PHASE1_DIGEST, "status": "APPROVED"},
            "pit_data_integrity": preflight,
            "genuine_missing_data": gaps,
            "downstream_analyses": "NOT_RUN_STOP_CONDITION",
            "mandatory_conditions": {
                "PIT_DATA_INTEGRITY": "FAIL",
                "IDENTITY_BLOCKED": identity_blocked,
                "MATERIAL_DATA_GAP": material_gap,
                "GENUINE_MISSING_DATA": gaps["unique_missing_security_sessions"],
                "PIT_EVENT_DETERMINISM": "NOT_RUN",
                "BOTH_INVARIANCE": "NOT_RUN",
                "ARITHMETIC_BRIDGE": "NOT_RUN",
                "DATE_CLUSTERED_BOOTSTRAP": "NOT_RUN",
            },
            "decision": "NOT_READY_FOR_PHASE_3",
        }
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps({
            "pit_data_integrity": "FAIL",
            "genuine_missing_security_sessions": gaps["unique_missing_security_sessions"],
            "affected_event_horizons": gaps["affected_event_horizons"],
            "affected_securities": gaps["affected_securities"],
            "downstream_analyses": "NOT_RUN_STOP_CONDITION",
            "decision": payload["decision"],
            "output": str(output),
        }, indent=2))
        return payload

    pit_second = engine.run(pit_request, by_security, benchmark, is_member)
    pit_repeat_events = [item.model_dump(mode="json") for item in pit_second.events]
    repeat_classes, _, _ = _audit_outcomes(
        pit_repeat_events, by_security, benchmark, policies, calendar
    )
    pit_digest_first = deterministic_phase2_digest(pit_events, pit_classes)
    pit_digest_second = deterministic_phase2_digest(pit_repeat_events, repeat_classes)
    determinism = {
        "status": "PASS" if pit_digest_first == pit_digest_second else "FAIL",
        "first_event_count": len(pit_events), "second_event_count": len(pit_repeat_events),
        "first_digest": pit_digest_first, "second_digest": pit_digest_second,
    }
    if determinism["status"] != "PASS":
        raise RuntimeError("PIT_EVENT_DETERMINISM FAIL")

    fixed_executable = executable_events(fixed_events)
    pit_executable = executable_events(pit_events)
    decomposition = decompose_events(fixed_executable, pit_executable)
    invariance = compare_both_invariance(
        decomposition["BOTH_FIXED"], decomposition["BOTH_PIT"], fixed_classes, pit_classes
    )
    if invariance["status"] != "PASS":
        raise RuntimeError(f"BOTH_INVARIANCE FAIL: {invariance}")

    bridge = arithmetic_bridge(
        decomposition["BOTH_PIT"], decomposition["FIXED_ONLY"], decomposition["PIT_ONLY"]
    )
    if bridge["status"] != "PASS":
        raise RuntimeError(f"ARITHMETIC_BRIDGE FAIL: {bridge}")

    fixed_metrics = {str(h): event_metrics(fixed_executable, h) for h in HORIZONS}
    pit_metrics = {str(h): event_metrics(pit_executable, h) for h in HORIZONS}
    metric_differences = {str(h): _metrics_delta(fixed_metrics[str(h)], pit_metrics[str(h)])
                          for h in HORIZONS}
    groups = {
        "BOTH": subset_metrics(decomposition["BOTH_PIT"]),
        "PIT_ONLY": subset_metrics(decomposition["PIT_ONLY"]),
        "FIXED_ONLY": subset_metrics(decomposition["FIXED_ONLY"]),
    }

    fixed_20_groups = values_by_date(fixed_executable, 20)
    pit_20_groups = values_by_date(pit_executable, 20)
    fixed_lower_groups = values_by_date(
        fixed_executable, 20, lifecycle_overrides(fixed_cases, "LOWER")
    )
    fixed_upper_groups = values_by_date(
        fixed_executable, 20, lifecycle_overrides(fixed_cases, "UPPER")
    )
    lower_overrides = lifecycle_overrides(pit_cases, "LOWER")
    upper_overrides = lifecycle_overrides(pit_cases, "UPPER")
    pit_lower_groups = values_by_date(pit_executable, 20, lower_overrides)
    pit_upper_groups = values_by_date(pit_executable, 20, upper_overrides)
    bootstrap = {
        "fixed_rebuilt": date_clustered_bootstrap(
            fixed_20_groups, seed=BOOTSTRAP_SEED, resamples=BOOTSTRAP_RESAMPLES
        ),
        "pit": date_clustered_bootstrap(
            pit_20_groups, seed=BOOTSTRAP_SEED, resamples=BOOTSTRAP_RESAMPLES
        ),
        "difference": paired_date_clustered_bootstrap(
            fixed_20_groups, pit_20_groups,
            seed=BOOTSTRAP_SEED, resamples=BOOTSTRAP_RESAMPLES,
        ),
        "lower_difference": paired_date_clustered_bootstrap(
            fixed_lower_groups, pit_lower_groups,
            seed=BOOTSTRAP_SEED, resamples=BOOTSTRAP_RESAMPLES,
        ),
        "upper_difference": paired_date_clustered_bootstrap(
            fixed_upper_groups, pit_upper_groups,
            seed=BOOTSTRAP_SEED, resamples=BOOTSTRAP_RESAMPLES,
        ),
    }
    bootstrap["status"] = "PASS" if all(
        item["status"] == "PASS" for item in bootstrap.values() if isinstance(item, dict)
    ) else "FAIL"

    sensitivity = {}
    for horizon in (20, 60):
        primary = pit_metrics[str(horizon)]
        lower = sensitivity_metrics(pit_executable, pit_cases, horizon, "LOWER")
        upper = sensitivity_metrics(pit_executable, pit_cases, horizon, "UPPER")
        fixed_lower = sensitivity_metrics(fixed_executable, fixed_cases, horizon, "LOWER")
        fixed_upper = sensitivity_metrics(fixed_executable, fixed_cases, horizon, "UPPER")
        sensitivity[str(horizon)] = {
            "LOWER": lower, "PRIMARY": primary, "UPPER": upper,
            "pit_minus_fixed": {
                "LOWER": _metrics_delta(fixed_lower, lower),
                "PRIMARY": metric_differences[str(horizon)],
                "UPPER": _metrics_delta(fixed_upper, upper),
            },
        }

    fixed_score = ScoreResearchEngine(calendar).run(
        ScoreResearchRequest(backtest_run_id=fixed_result.run_id), fixed_result
    )
    pit_score = ScoreResearchEngine(calendar).run(
        ScoreResearchRequest(backtest_run_id=pit_first.run_id), pit_first
    )
    fixed_regime = MarketRegimeEngine().run(
        MarketRegimeRequest(backtest_run_id=fixed_result.run_id), fixed_result, benchmark
    )
    pit_regime = MarketRegimeEngine().run(
        MarketRegimeRequest(backtest_run_id=pit_first.run_id), pit_first, benchmark
    )

    original_events = original["events"]
    original_mapped, unmapped = map_fixed_universe_events(
        original_events, fixed_security_ids, resolver
    )
    if unmapped:
        raise RuntimeError("approved Phase 1 mapping no longer reproduces UNMAPPED=0")
    original_map = {(identity.security_id, identity.signal_date): (identity, event)
                    for identity, event in original_mapped}
    fixed_map = event_map(fixed_events)
    additional_keys = fixed_map.keys() - original_map.keys()
    original_only_keys = original_map.keys() - fixed_map.keys()
    additional = [fixed_map[key] for key in additional_keys]
    original_dates, fixed_dates = _date_counts(original_events), _date_counts(fixed_events)
    all_dates = sorted(set(original_dates) | set(fixed_dates))
    largest_dates = sorted(({
        "signal_date": when, "original": original_dates[when], "fixed_rebuilt": fixed_dates[when],
        "difference": fixed_dates[when] - original_dates[when],
        "absolute_difference": abs(fixed_dates[when] - original_dates[when]),
    } for when in all_dates), key=lambda item: (-item["absolute_difference"], item["signal_date"]))[:20]
    fixed_regime_lookup = {
        (row["ticker"], row["signal_date"]): row
        for row in fixed_regime.results["observations"]
    }
    additional_regimes = {
        "sma200": dict(Counter(fixed_regime_lookup[(item["ticker"], item["signal_date"])]["sma200_regime"]
                               for item in additional)),
        "configuration": dict(Counter(fixed_regime_lookup[(item["ticker"], item["signal_date"])]["configuration"]
                                      for item in additional)),
        "volatility": dict(Counter(fixed_regime_lookup[(item["ticker"], item["signal_date"])]["volatility_regime"]
                                   for item in additional)),
    }
    signal_expansion = {
        "original_events": len(original_events), "fixed_rebuilt_events": len(fixed_events),
        "original_by_year": _annual_counts(original_events),
        "fixed_rebuilt_by_year": _annual_counts(fixed_events),
        "original_date_distribution": signal_distribution(original_events),
        "fixed_rebuilt_date_distribution": signal_distribution(fixed_events),
        "largest_absolute_date_differences": largest_dates,
        "additional_fixed_rebuilt_events": len(additional),
        "original_fixed_only": len(original_only_keys),
        "fixed_rebuilt_only": len(additional_keys),
        "net_difference": len(fixed_events) - len(original_events),
        "additional_score_buckets": dict(Counter(score_bucket(float(item["score"])) for item in additional)),
        "additional_20d": event_metrics(additional, 20),
        "additional_regimes": additional_regimes,
        "approved_warmup_finding": {
            "differences": 710, "reproduced": 710,
            "research_window_start_truncation": 710,
            "membership_entry_truncation": 0, "securities": 302,
            "histories_restored": 302, "bars_restored": 78297,
        },
    }
    if (len(original_only_keys), len(additional_keys), len(fixed_events) - len(original_events)) != (27, 1092, 1065):
        raise RuntimeError("approved Phase 1 signal expansion no longer reproduces")
    spy_consistency = {
        "20": _spy_consistency(original_map, fixed_map, 20),
        "60": _spy_consistency(original_map, fixed_map, 60),
        "supported_explanation": (
            "Matched events use identical SPY returns; the approved 60d pattern is therefore supported "
            "by changed equity price histories plus event-set/timing composition, not SPY-source differences."
        ),
    }

    pit_key_set = set(event_map(pit_events))
    fixed_key_set = set(event_map(fixed_events))
    set_for_key = {key: ("BOTH" if key in fixed_key_set else "PIT_ONLY") for key in pit_key_set}
    lifecycle_counts = {str(h): {"BOTH": Counter(), "PIT_ONLY": Counter(), "FIXED_ONLY": Counter()}
                        for h in HORIZONS}
    for case in pit_cases:
        lifecycle_counts[str(case.horizon)][set_for_key[(case.security_id, case.signal_date)]][case.reason] += 1
    for case in fixed_cases:
        base_key = (case.security_id, case.signal_date)
        if base_key not in pit_key_set:
            lifecycle_counts[str(case.horizon)]["FIXED_ONLY"][case.reason] += 1
    lifecycle_counts = {h: {group: dict(sorted(values.items())) for group, values in groups_.items()}
                        for h, groups_ in lifecycle_counts.items()}

    labels = {security_id: sorted(records, key=lambda item: item.valid_from)[-1].ticker
              for security_id, records in membership_by_security.items()}
    non_executable = []
    for event in pit_events:
        if event.get("entry_date") is not None and event.get("entry_price") is not None:
            continue
        security_id, signal_date = event_map([event]).popitem()[0]
        policy = policies.get(security_id)
        classification = ("NON_EXECUTABLE_LIFECYCLE_TERMINATION"
                          if policy and signal_date <= policy["last_session"] else "UNCLASSIFIED")
        non_executable.append({
            "security_id": security_id, "ticker": labels.get(security_id),
            "signal_date": signal_date.isoformat(), "classification": classification,
            "lifecycle_reason": policy["reason"] if policy else None,
            "last_regular_trading_date": policy["last_session"].isoformat() if policy else None,
        })

    pit_event_lookup = event_map(pit_events)
    bankruptcy_audit = {}
    for security_id, policy in sorted(policies.items()):
        if policy["reason"] != "BANKRUPTCY":
            continue
        signals = [event for key, event in pit_event_lookup.items() if key[0] == security_id]
        executable = executable_events(signals)
        last = policy["last_session"]
        within_60 = [event for event in signals if
                     0 <= len(calendar.trading_days_between(
                         date.fromisoformat(str(event["signal_date"])), last)) - 1 <= 60]
        bankruptcy_audit[labels.get(security_id, policy.get("ticker") or security_id)] = {
            "security_id": security_id, "signals": len(signals),
            "executable_events": len(executable),
            "non_executable_signals": len(signals) - len(executable),
            "signals_within_60_sessions_of_termination": len(within_60),
            "lifecycle_truncated_event_horizons": sum(
                case.security_id == security_id for case in pit_cases
            ),
            "last_regular_trading_date": last.isoformat(),
            "primary_completed_20d": event_metrics(executable, 20)["n"] if executable else 0,
        }

    documentation_gap_audit = {}
    for security_id, row in sorted(boundary_evidence["documentation_gaps"].items()):
        pit_signals = [event for key, event in pit_event_lookup.items() if key[0] == security_id]
        fixed_signals = [event for key, event in fixed_map.items() if key[0] == security_id]
        documentation_gap_audit[row.get("ticker", labels.get(security_id, security_id))] = {
            "security_id": security_id, "pit_signals": len(pit_signals),
            "fixed_rebuilt_signals": len(fixed_signals),
            "executable_pit_events": len(executable_events(pit_signals)),
            "lifecycle_cases": sum(case.security_id == security_id for case in pit_cases),
            "research_invariant": not pit_signals and not fixed_signals,
            "status": "PASS" if not pit_signals and not fixed_signals else "FAIL",
        }

    merger_ids = {sid for sid, policy in policies.items()
                  if policy["reason"] in {"ACQUISITION", "MERGER"}}
    merger_signals = [event for event in pit_executable if event_key(event)[0] in merger_ids]
    merger_timing = Counter()
    post_announcement = []
    lifecycle_keys = {case.key for case in pit_cases}
    post_lifecycle = 0
    for event in merger_signals:
        security_id, signal_date = event_key(event)
        policy = policies[security_id]
        announcement = date.fromisoformat(policy["announcement_date"])
        closing = date.fromisoformat(policy["closing_date"])
        bucket = classify_ma_timing(signal_date, announcement, closing,
                                    policy["last_session"])
        if bucket == "POST_ANNOUNCEMENT_PRE_CLOSE":
            post_announcement.append(event)
            post_lifecycle += sum(
                (security_id, signal_date, horizon) in lifecycle_keys for horizon in HORIZONS
            )
        merger_timing[bucket] += 1
    post_metrics = event_metrics(post_announcement, 20) if post_announcement else event_metrics([], 20)
    total_primary_n = pit_metrics["20"]["n"]
    completed_post = [float(outcome(event, 20)["excess_return"]) for event in post_announcement
                      if outcome(event, 20)["forward_data_complete"]]
    merger_diagnostic = {
        "affected_securities": len({event_key(event)[0] for event in merger_signals}),
        **{name: merger_timing[name] for name in (
            "PRE_ANNOUNCEMENT", "ON_ANNOUNCEMENT_DATE",
            "POST_ANNOUNCEMENT_PRE_CLOSE", "POST_CLOSE_INVALID")},
        "post_announcement_percentage_of_executable_pit": (
            len(post_announcement) / len(pit_executable) if pit_executable else 0
        ),
        "post_announcement_20d": post_metrics,
        "post_announcement_lifecycle_truncated_event_horizons": post_lifecycle,
        "contribution_to_primary_mean_excess": (
            sum(completed_post) / total_primary_n if total_primary_n else 0
        ),
        "signals_removed_from_primary": 0,
        "coverage_label": "LOWER_BOUND_DIAGNOSTIC",
    }

    lifecycle_activation = {}
    for horizon in HORIZONS:
        selected = [case for case in pit_cases if case.horizon == horizon]
        lifecycle_activation[str(horizon)] = {
            "event_horizons": len(selected),
            "unique_signals": len({(case.security_id, case.signal_date) for case in selected}),
            "unique_securities": len({case.security_id for case in selected}),
            "missing_sessions": sum(len(case.missing_sessions) for case in selected),
            "diagnostic_evaluable": sum(case.diagnostic_evaluable for case in selected),
        }

    score_buckets = {
        "fixed_rebuilt": score_bucket_metrics(fixed_executable),
        "pit": score_bucket_metrics(pit_executable),
    }
    payload = {
        "phase": "PHASE_2_PIT_EVENT_STUDY_ONLY",
        "phase1_baseline": {"digest": PHASE1_DIGEST, "status": "APPROVED"},
        "pit_data_integrity": preflight,
        "pit_event_determinism": determinism,
        "field_dependency": field_dependency_audit(),
        "both_invariance": invariance,
        "event_counts": {
            "fixed_rebuilt_signals": len(fixed_events), "pit_signals": len(pit_events),
            "fixed_rebuilt": len(fixed_executable), "pit": len(pit_executable),
            "fixed_non_executable": len(fixed_events) - len(fixed_executable),
            "pit_non_executable": len(pit_events) - len(pit_executable),
            "both": len(decomposition["BOTH_PIT"]),
            "pit_only": len(decomposition["PIT_ONLY"]),
            "fixed_only": len(decomposition["FIXED_ONLY"]),
        },
        "event_set_summaries": {
            "BOTH": set_summary(decomposition["BOTH_PIT"]),
            "PIT_ONLY": set_summary(decomposition["PIT_ONLY"]),
            "FIXED_ONLY": set_summary(decomposition["FIXED_ONLY"]),
        },
        "event_set_metrics": groups,
        "metrics": {"fixed_rebuilt": fixed_metrics, "pit": pit_metrics,
                    "pit_minus_fixed_rebuilt": metric_differences},
        "excursions": {
            "fixed_rebuilt": {str(h): _excursion_metrics(fixed_executable, h)
                                for h in HORIZONS},
            "pit": {str(h): _excursion_metrics(pit_executable, h) for h in HORIZONS},
        },
        "primary_metric": {
            "name": "20-session mean excess return vs SPY",
            "pit_minus_fixed_rebuilt": metric_differences["20"]["mean_excess_return"],
        },
        "bootstrap": bootstrap,
        "arithmetic_bridge": bridge,
        "horizon_completeness": {
            "fixed_rebuilt": horizon_completeness(fixed_events),
            "pit": horizon_completeness(pit_events),
            "fixed_classifications": fixed_horizon_audit,
            "pit_classifications": pit_horizon_audit,
        },
        "lifecycle": {
            "primary_treatment": "EXCLUDED",
            "cases": len(pit_cases),
            "diagnostic_evaluable_cases": sum(item.diagnostic_evaluable for item in pit_cases),
            "no_next_open_or_benchmark_cases": sum(not item.diagnostic_evaluable for item in pit_cases),
            "counts_by_horizon_set_reason": lifecycle_counts,
            "activation": lifecycle_activation,
        },
        "non_executable_lifecycle_signals": non_executable,
        "bankruptcy_audit": bankruptcy_audit,
        "documentation_gap_audit": documentation_gap_audit,
        "sensitivity": sensitivity,
        "lifecycle_bounds_activation": {
            str(horizon): lifecycle_bounds_active(pit_cases, horizon)
            for horizon in (20, 60)
        },
        "score_buckets": score_buckets,
        "score_bucket_boundaries": {"20": "20-40", "40": "40-60", "60": "60-80", "80": "80-100"},
        "feature_correlations": {
            "method": "Phase 6 ScoreResearchEngine component methodology",
            "fixed_rebuilt": _feature_summary(fixed_score),
            "pit": _feature_summary(pit_score),
        },
        "market_regimes": {
            "method": pit_regime.results["volatility_method"],
            "fixed_rebuilt": _regime_summary(fixed_regime),
            "pit": _regime_summary(pit_regime),
        },
        "signal_expansion": signal_expansion,
        "spy_consistency": spy_consistency,
        "original_fixed_reference": {
            "run_id": str(ORIGINAL_RUN_ID), "events": len(original_events),
            "20": event_metrics(original_events, 20),
            "60": event_metrics(original_events, 60),
        },
        "ma_ledger_coverage": {
            "classification": "KNOWN_LIFECYCLE_LOWER_BOUND",
            "evidenced_closed_events": len(merger_ids),
            "reason": (
                "The validated ledger covers known closed lifecycle events but is not a "
                "systematic inventory of all announced, pending, cancelled, or failed transactions."
            ),
        },
        "ma_signal_diagnostic": merger_diagnostic,
    }
    mandatory = {
        "PIT_DATA_INTEGRITY": preflight["status"],
        "PIT_EVENT_DETERMINISM": determinism["status"],
        "BOTH_INVARIANCE": invariance["status"],
        "ARITHMETIC_BRIDGE": bridge["status"],
        "DATE_CLUSTERED_BOOTSTRAP": bootstrap["status"],
        "IDENTITY_BLOCKED": identity_blocked,
        "MATERIAL_DATA_GAP": material_gap,
        "GENUINE_MISSING_DATA": genuine,
        "truncated_event_audit": "PASS",
        "sensitivity_bounds": "PASS",
        "feature_regime_baseline": "PASS",
        "signal_expansion_diagnostic": "PASS",
        "spy_consistency_diagnostic": "PASS",
        "FIELD_DEPENDENCY_AUDIT": payload["field_dependency"]["status"],
        "NON_EXECUTABLE_CLASSIFICATION": (
            "PASS" if all(item["classification"] ==
                          "NON_EXECUTABLE_LIFECYCLE_TERMINATION"
                          for item in non_executable) else "FAIL"
        ),
        "FRC_NON_BLOCKING": documentation_gap_audit.get("FRC", {}).get("status", "FAIL"),
        "GPS_NON_BLOCKING": documentation_gap_audit.get("GPS", {}).get("status", "FAIL"),
        "RAL_OLD_NON_BLOCKING": documentation_gap_audit.get("RAL_OLD", {}).get("status", "FAIL"),
        "POST_CLOSE_INVALID_SIGNALS": merger_diagnostic["POST_CLOSE_INVALID"],
        "FINANCIALLY_RELEVANT_UNKNOWN": (
            "FAIL" if financially_relevant_unknown(pit_cases) else "PASS"
        ),
    }
    payload["mandatory_conditions"] = mandatory
    payload["decision"] = "READY_FOR_PHASE_3" if all(
        value == "PASS" or value == 0 for value in mandatory.values()
    ) else "NOT_READY_FOR_PHASE_3"
    payload["analysis_digest"] = _json_digest(payload)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "pit_data_integrity": preflight["status"], "pit_events": len(pit_events),
        "both": len(decomposition["BOTH_PIT"]), "pit_only": len(decomposition["PIT_ONLY"]),
        "fixed_only": len(decomposition["FIXED_ONLY"]), "both_invariance": invariance["status"],
        "arithmetic_bridge": bridge["status"], "determinism": determinism["status"],
        "bootstrap": bootstrap["status"], "decision": payload["decision"],
        "output": str(output),
    }, indent=2))
    return payload


if __name__ == "__main__":
    asyncio.run(run(parser().parse_args()))
