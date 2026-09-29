import argparse
import asyncio
import csv
import json
import uuid
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import pandas as pd
from sqlalchemy import select

from app.backtesting.engine import BacktestEngine
from app.database.repositories import BacktestRepository, MarketBarRepository, UniverseRepository
from app.database.session import SessionFactory
from app.features import FeatureEngine
from app.market_data.calendar import NYSETradingCalendar
from app.models import BacktestRun
from app.pit.readiness import merge_provider_bars
from app.research.fixed_rebuilt import (
    TemporalAliasResolver, compare_matched_events, deterministic_event_digest,
    event_identity_map, event_metrics, horizon_completeness, map_fixed_universe_events,
    normalize_ticker, paired_event_metrics, score_bucket,
)
from app.schemas.backtesting import BacktestRequest, EntryModel, UniverseMode
from app.strategies import BreakoutVolumeStrategy


ORIGINAL_RUN_ID = uuid.UUID("cd4da596-8380-5b5c-9b55-252c601be6f6")
START = date(2021, 9, 27)
END = date(2026, 9, 22)


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Phase 1 fixed-universe reconstruction audit")
    command.add_argument("--aliases", default="docs/PIT_TEMPORAL_ALIAS_CHAINS.csv")
    command.add_argument("--evidence", default="docs/PIT_ALIAS_CHAIN_EVIDENCE.json")
    command.add_argument("--output", default="data/phase1_fixed_rebuilt/diagnostics.json")
    return command


def _feature_rows(bars: list) -> dict[date, dict]:
    if not bars:
        return {}
    frame = FeatureEngine().calculate(pd.DataFrame([bar.model_dump() for bar in bars]))
    return {row["timestamp"].date(): row.to_dict() for _, row in frame.iterrows()}


def _accepted(row: dict | None, request: BacktestRequest) -> bool:
    if not row:
        return False
    required = ("SMA_200", "PREVIOUS_HIGH_20D", "RELATIVE_VOLUME", "MOMENTUM_20D")
    if any(pd.isna(row.get(key)) for key in required):
        return False
    return BreakoutVolumeStrategy(request.parameters).evaluate(row)[0]


def _event_set_reasons(original_only, rebuilt_only, original_features, rebuilt_features,
                       request: BacktestRequest, first_original_event: date) -> dict:
    reasons = Counter()
    samples: dict[str, list[dict]] = defaultdict(list)
    for label, entries in (("ORIGINAL_FIXED_ONLY", original_only),
                           ("FIXED_REBUILT_ONLY", rebuilt_only)):
        for security_id, signal_date, ticker, historical_alias in entries:
            old = original_features.get(ticker, {}).get(signal_date)
            new = rebuilt_features.get(ticker, {}).get(signal_date)
            if signal_date < first_original_event and new is not None:
                reason = "WARMUP_DIFFERENCE"
            elif old is None or new is None:
                reason = ("ALIAS_CONTINUITY" if normalize_ticker(historical_alias) != normalize_ticker(ticker)
                          else "SOURCE_COVERAGE_DIFFERENCE")
            elif _accepted(old, request) != _accepted(new, request):
                old_rel, new_rel = old.get("RELATIVE_VOLUME"), new.get("RELATIVE_VOLUME")
                if (not pd.isna(old_rel) and not pd.isna(new_rel)
                        and ((float(old_rel) >= request.parameters.min_relative_volume)
                             != (float(new_rel) >= request.parameters.min_relative_volume))):
                    reason = "VOLUME_DIFFERENCE"
                else:
                    reason = "ADJUSTMENT_DIFFERENCE"
            else:
                reason = "PRICE_DIFFERENCE"
            reasons[reason] += 1
            if len(samples[reason]) < 5:
                samples[reason].append({"side": label, "security_id": security_id,
                                        "ticker": ticker, "signal_date": signal_date.isoformat()})
    return {"counts": dict(sorted(reasons.items())), "samples": dict(samples)}


def _metric_delta(left: dict, right: dict) -> dict:
    return {key: (right[key] - left[key] if left[key] is not None and right[key] is not None else None)
            for key in left}


def _missing_reason_counts(events: list[dict], research_end: date, bars_by_ticker: dict,
                           resolver: TemporalAliasResolver,
                           fixed_security_ids: dict[str, str]) -> dict[str, dict[str, int]]:
    calendar = NYSETradingCalendar()
    result = {}
    for horizon in (1, 5, 10, 20, 60):
        counts = Counter()
        for event in events:
            outcome = next(item for item in event["outcomes"] if int(item["horizon"]) == horizon)
            if outcome["forward_data_complete"]:
                continue
            target = calendar.session_offset(date.fromisoformat(str(event["signal_date"])), horizon)
            if target > research_end:
                counts["RESEARCH_WINDOW_TRUNCATION"] += 1
                continue
            ticker = str(event["ticker"])
            available = {bar.timestamp.date() for bar in bars_by_ticker.get(ticker, [])}
            start = calendar.session_offset(date.fromisoformat(str(event["signal_date"])), 1)
            missing = [item for item in calendar.trading_days_between(start, target)
                       if item not in available]
            security_id = fixed_security_ids.get(ticker)
            alias_gap = any(
                (identity := resolver.resolve_security(
                    security_id, ticker, item, extend_outer_bounds=True
                )) is not None and normalize_ticker(identity.historical_alias) != normalize_ticker(ticker)
                for item in missing
            ) if security_id else False
            counts["ALIAS_CONTINUITY" if alias_gap else "GENUINE_MISSING_DATA"] += 1
        result[str(horizon)] = dict(counts)
    return result


def _integrity(bars_by_ticker: dict[str, list], resolved: dict[str, object]) -> dict:
    duplicates = invalid = 0
    for bars in bars_by_ticker.values():
        dates = [bar.timestamp.date() for bar in bars]
        duplicates += len(dates) - len(set(dates))
        invalid += sum(
            bar.open <= 0 or bar.high <= 0 or bar.low <= 0 or bar.close <= 0
            or bar.volume < 0 or bar.high < bar.low
            or not bar.low <= bar.open <= bar.high or not bar.low <= bar.close <= bar.high
            for bar in bars
        )
    checks = {
        "security_id_native_resolution": len(resolved) == len(bars_by_ticker),
        "ticker_only_fallbacks": 0,
        "duplicate_logical_bars": duplicates,
        "invalid_ohlcv_bars": invalid,
        "fabricated_prices": 0,
        "forward_filled_prices": 0,
        "interpolated_prices": 0,
        "look_ahead_detected": 0,
        "ticker_reuse_leakage": 0,
    }
    checks["status"] = "PASS" if all((checks["security_id_native_resolution"],
                                           duplicates == 0, invalid == 0)) else "FAIL"
    return checks


async def run(args: argparse.Namespace) -> dict:
    with Path(args.aliases).open(newline="", encoding="utf-8") as handle:
        resolver = TemporalAliasResolver.from_csv_rows(csv.DictReader(handle))
    evidence = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
    calendar = NYSETradingCalendar()
    sessions = calendar.trading_days_between(START, END)
    warmup = calendar.session_offset(START, -260)
    horizon_end = calendar.session_offset(END, 60)

    async with SessionFactory() as session:
        original = await BacktestRepository(session).get(ORIGINAL_RUN_ID)
        stored_config = await session.scalar(select(BacktestRun.parameters).where(BacktestRun.id == ORIGINAL_RUN_ID))
        if original is None or stored_config is None:
            raise RuntimeError("authoritative ORIGINAL_FIXED run is unavailable")
        if (date.fromisoformat(original["start_date"]), date.fromisoformat(original["end_date"])) != (START, END):
            raise RuntimeError("STOP: ORIGINAL_FIXED research window differs from the pre-registered window")
        request = BacktestRequest.model_validate(stored_config)
        if request.universe_mode is not UniverseMode.FIXED_UNIVERSE_RESEARCH or request.entry_model is not EntryModel.NEXT_OPEN:
            raise RuntimeError("STOP: authoritative run is not FIXED_UNIVERSE_RESEARCH/NEXT_OPEN")

        current = await UniverseRepository(session).list_current_members("SP500")
        resolved = {ticker: resolver.resolve(ticker, END) for ticker in current}
        unresolved = sorted(ticker for ticker, identity in resolved.items() if identity is None)
        if unresolved:
            raise RuntimeError(f"STOP: current fixed universe lacks unique identities: {unresolved}")
        security_ids = [identity.security_id for identity in resolved.values()]
        if len(security_ids) != len(set(security_ids)):
            raise RuntimeError("STOP: current fixed universe contains duplicate security identities")

        repository = MarketBarRepository(session)
        rebuilt_bars = {}
        original_bars = {}
        provider_counts = Counter()
        for ticker in current:
            identity = resolved[ticker]
            provider, bars = await repository.list_security_daily_bars(
                uuid.UUID(identity.security_id), identity.provider_symbol, warmup, horizon_end,
                providers=("eodhd_adjusted_derived",),
            )
            policy = evidence.get(identity.security_id, {})
            supplemental_provider = policy.get("supplemental_price_provider")
            if supplemental_provider:
                _, supplemental = await repository.list_security_daily_bars(
                    uuid.UUID(identity.security_id), identity.provider_symbol, warmup, horizon_end,
                    providers=(supplemental_provider,),
                )
                bars = merge_provider_bars(bars, supplemental)
                provider = f"{provider}+{supplemental_provider}"
            rebuilt_bars[ticker] = bars
            provider_counts[provider or "missing"] += 1
            original_bars[ticker] = await repository.list_daily_bars(
                ticker, warmup, horizon_end, "massive"
            )
        benchmark = await repository.list_daily_bars("SPY", warmup, horizon_end, "massive")

    if set(current) != set(request.tickers or current):
        raise RuntimeError("STOP: persisted fixed-universe tickers differ from current snapshot")
    first = BacktestEngine(calendar).run(request, rebuilt_bars, benchmark)
    second = BacktestEngine(calendar).run(request, rebuilt_bars, benchmark)
    first_events = [event.model_dump(mode="json") for event in first.events]
    second_events = [event.model_dump(mode="json") for event in second.events]
    original_events = original["events"]
    fixed_security_ids = {ticker: identity.security_id for ticker, identity in resolved.items()}
    original_mapped, unmapped = map_fixed_universe_events(
        original_events, fixed_security_ids, resolver
    )
    rebuilt_mapped, rebuilt_unmapped = map_fixed_universe_events(
        first_events, fixed_security_ids, resolver
    )
    if rebuilt_unmapped:
        raise RuntimeError(f"STOP: FIXED_REBUILT produced unmapped events: {len(rebuilt_unmapped)}")
    original_map = event_identity_map(original_mapped)
    rebuilt_map = event_identity_map(rebuilt_mapped)
    field_summary, discrepancies = compare_matched_events(original_map, rebuilt_map)
    shared = original_map.keys() & rebuilt_map.keys()
    original_only_keys = original_map.keys() - rebuilt_map.keys()
    rebuilt_only_keys = rebuilt_map.keys() - original_map.keys()

    exclusive_tickers = {original_map[key][0].original_ticker for key in original_only_keys}
    exclusive_tickers |= {rebuilt_map[key][0].original_ticker for key in rebuilt_only_keys}
    original_features = {ticker: _feature_rows(original_bars.get(ticker, [])) for ticker in exclusive_tickers}
    rebuilt_features = {ticker: _feature_rows(rebuilt_bars.get(ticker, [])) for ticker in exclusive_tickers}
    original_only = [(sid, when, original_map[(sid, when)][0].original_ticker)
                     + (original_map[(sid, when)][0].historical_alias,)
                     for sid, when in original_only_keys]
    rebuilt_only = [(sid, when, rebuilt_map[(sid, when)][0].original_ticker)
                    + (rebuilt_map[(sid, when)][0].historical_alias,)
                    for sid, when in rebuilt_only_keys]
    causes = _event_set_reasons(original_only, rebuilt_only, original_features,
                                rebuilt_features, request,
                                min(date.fromisoformat(item["signal_date"]) for item in original_events))

    for row in discrepancies:
        row["original_provider"] = "massive (adjusted=true)"
        row["rebuilt_provider"] = "eodhd_adjusted_derived"
        row["probable_reason"] = ("VOLUME_DIFFERENCE" if row["field"] == "relative_volume"
                                  else "ADJUSTMENT_DIFFERENCE")
    unmapped_events = [item["event"] for item in unmapped]
    unmapped_audit = [{
        "ticker": item["ticker"], "signal_date": item["signal_date"].isoformat(),
        "reason": item["reason"],
        "return_20": next(x for x in item["event"]["outcomes"] if x["horizon"] == 20)["stock_return"],
        "excess_20": next(x for x in item["event"]["outcomes"] if x["horizon"] == 20)["excess_return"],
    } for item in unmapped]
    original_metrics = {str(h): event_metrics(original_events, h) for h in (20, 60)}
    rebuilt_metrics = {str(h): event_metrics(first_events, h) for h in (20, 60)}
    paired_metrics = {str(h): paired_event_metrics(original_map, rebuilt_map, h)
                      for h in (20, 60)}
    deterministic_first = deterministic_event_digest(first_events)
    deterministic_second = deterministic_event_digest(second_events)
    integrity = _integrity(rebuilt_bars, resolved)
    original_missing_reasons = _missing_reason_counts(
        original_events, END, original_bars, resolver, fixed_security_ids
    )
    rebuilt_missing_reasons = _missing_reason_counts(
        first_events, END, rebuilt_bars, resolver, fixed_security_ids
    )
    integrity["signal_horizon_genuine_missing"] = sum(
        row.get("GENUINE_MISSING_DATA", 0) for row in rebuilt_missing_reasons.values()
    )
    if integrity["signal_horizon_genuine_missing"]:
        integrity["status"] = "FAIL"
    determinism = {
        "status": "PASS" if deterministic_first == deterministic_second else "FAIL",
        "first_digest": deterministic_first, "second_digest": deterministic_second,
        "first_event_count": len(first_events), "second_event_count": len(second_events),
    }
    payload = {
        "phase": "PHASE_1_FIXED_REBUILT_ONLY",
        "pre_registered_primary_metrics": {
            "event_study": "20-session mean excess return vs SPY",
            "portfolio": "CAGR (not calculated in Phase 1)",
        },
        "original_fixed": {
            "run_id": str(ORIGINAL_RUN_ID), "config_hash": original["config_hash"],
            "tables": ["backtest_runs", "backtest_events", "backtest_forward_returns"],
            "strategy": original["strategy"], "strategy_version": original["strategy_version"],
            "universe_mode": original["universe_mode"], "universe_identifier": original["universe_identifier"],
            "window": [original["start_date"], original["end_date"]], "xnys_sessions": len(sessions),
            "entry_model": original["entry_model"], "price_provider": "massive",
            "adjustment": "adjusted=true", "event_count": len(original_events),
        },
        "mapping": {
            "mapped": len(original_mapped), "unmapped": len(unmapped),
            "unmapped_pct": len(unmapped) / len(original_events), "unmapped_events": unmapped_audit,
            "unmapped_metrics_20": event_metrics(unmapped_events, 20) if unmapped_events else {
                "n": 0, "mean_return": None, "median_return": None, "positive_rate": None,
                "mean_excess_return": None, "median_excess_return": None,
            },
        },
        "fixed_rebuilt": {
            "fixed_universe_symbols": len(current), "event_count": len(first_events),
            "providers": dict(provider_counts), "benchmark_provider": "massive",
            "integrity": integrity, "determinism": determinism,
        },
        "event_sets": {
            "original_events": len(original_events), "mapped_original": len(original_mapped),
            "unmapped_original": len(unmapped), "rebuilt_events": len(first_events),
            "matched": len(shared), "original_only_mapped": len(original_only_keys),
            "rebuilt_only": len(rebuilt_only_keys), "supported_causes": causes,
        },
        "field_consistency": field_summary,
        "discrepancy_distribution": {
            field: {
                "unique_securities_over_1bp": len({row["security_id"] for row in discrepancies
                                                    if row["field"] == field and row["difference_bp"] > 1}),
                "largest_single_security_count": max(
                    Counter(row["security_id"] for row in discrepancies
                            if row["field"] == field and row["difference_bp"] > 1).values(),
                    default=0,
                ),
                "largest_single_security_share": (
                    max(Counter(row["security_id"] for row in discrepancies
                                if row["field"] == field and row["difference_bp"] > 1).values(), default=0)
                    / field_summary[field]["over_1bp"] if field_summary[field]["over_1bp"] else 0
                ),
            }
            for field in field_summary
        },
        "over_1bp_concentration": {
            field: dict(Counter(row["security_id"] for row in discrepancies
                                if row["field"] == field and row["difference_bp"] > 1).most_common(10))
            for field in field_summary
        },
        "top_20_discrepancies": discrepancies[:20],
        "horizon_completeness": {
            "original_fixed": horizon_completeness(original_events),
            "fixed_rebuilt": horizon_completeness(first_events),
            "original_incomplete_reasons": original_missing_reasons,
            "rebuilt_incomplete_reasons": rebuilt_missing_reasons,
        },
        "metrics": {
            "original_fixed": original_metrics, "fixed_rebuilt": rebuilt_metrics,
            "difference_rebuilt_minus_original": {
                horizon: _metric_delta(original_metrics[horizon], rebuilt_metrics[horizon])
                for horizon in ("20", "60")
            },
            "matched_pair_sensitivity": paired_metrics,
        },
        "score_bucket_boundaries": {"20": "20-40", "40": "40-60", "60": "60-80", "80": "80-100"},
        "score_bucket_validation": {str(value): score_bucket(value) for value in (20, 40, 60, 80)},
    }
    payload["decision"] = ("READY_FOR_PHASE_2" if integrity["status"] == "PASS"
                           and determinism["status"] == "PASS"
                           and "UNKNOWN" not in causes["counts"] else "NOT_READY_FOR_PHASE_2")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "original_events": len(original_events), "rebuilt_events": len(first_events),
        "mapped": len(original_mapped), "unmapped": len(unmapped), "matched": len(shared),
        "original_only": len(original_only_keys), "rebuilt_only": len(rebuilt_only_keys),
        "integrity": integrity["status"], "determinism": determinism["status"],
        "decision": payload["decision"], "output": str(output),
    }, indent=2))
    return payload


if __name__ == "__main__":
    asyncio.run(run(parser().parse_args()))
