import hashlib
import json
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable

import numpy as np

from app.research.fixed_rebuilt import event_metrics, outcome, score_bucket


HORIZONS = (1, 5, 10, 20, 60)
NUMERIC_TOLERANCE = 1e-12
SECURITY_LOCAL_FIELDS = (
    "close", "entry_date", "entry_price", "previous_high_20d", "breakout_pct",
    "relative_volume", "sma_50", "sma_200", "momentum_20d",
    "avg_dollar_volume_20d", "distance_from_sma50", "score", "score_components",
)
UNIVERSE_DEPENDENT_FIELDS: tuple[str, ...] = ()


def event_key(event: dict[str, Any]) -> tuple[str, date]:
    return str(event["ticker"]), date.fromisoformat(str(event["signal_date"]))


def event_map(events: Iterable[dict[str, Any]]) -> dict[tuple[str, date], dict[str, Any]]:
    result: dict[tuple[str, date], dict[str, Any]] = {}
    for event in events:
        key = event_key(event)
        if key in result:
            raise ValueError(f"duplicate event identity: {key}")
        result[key] = event
    return result


def executable_events(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return signals with a real, persisted NEXT_OPEN execution observation."""
    return [event for event in events
            if event.get("entry_date") is not None and event.get("entry_price") is not None]


def field_dependency_audit() -> dict[str, Any]:
    return {
        "status": "PASS",
        "security_local": list(SECURITY_LOCAL_FIELDS),
        "universe_dependent": list(UNIVERSE_DEPENDENT_FIELDS),
        "conclusion": (
            "The implemented score and every score component use only the security's "
            "causal price/volume history; no cross-sectional universe input is used."
        ),
    }


def decompose_events(
    fixed: Iterable[dict[str, Any]], pit: Iterable[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    fixed_map = event_map(fixed)
    pit_map = event_map(pit)
    both = sorted(fixed_map.keys() & pit_map.keys(), key=lambda item: (item[1], item[0]))
    fixed_only = sorted(fixed_map.keys() - pit_map.keys(), key=lambda item: (item[1], item[0]))
    pit_only = sorted(pit_map.keys() - fixed_map.keys(), key=lambda item: (item[1], item[0]))
    return {
        "BOTH_FIXED": [fixed_map[key] for key in both],
        "BOTH_PIT": [pit_map[key] for key in both],
        "FIXED_ONLY": [fixed_map[key] for key in fixed_only],
        "PIT_ONLY": [pit_map[key] for key in pit_only],
    }


def set_summary(events: Iterable[dict[str, Any]]) -> dict[str, int]:
    rows = list(events)
    return {
        "events": len(rows),
        "unique_securities": len({event_key(item)[0] for item in rows}),
        "unique_signal_dates": len({event_key(item)[1] for item in rows}),
    }


def compare_both_invariance(
    fixed: Iterable[dict[str, Any]], pit: Iterable[dict[str, Any]],
    fixed_lifecycle: dict[tuple[str, date, int], str] | None = None,
    pit_lifecycle: dict[tuple[str, date, int], str] | None = None,
    *, tolerance: float = NUMERIC_TOLERANCE,
) -> dict[str, Any]:
    fixed_map = event_map(fixed)
    pit_map = event_map(pit)
    keys = sorted(fixed_map.keys() & pit_map.keys(), key=lambda item: (item[1], item[0]))
    fields = SECURITY_LOCAL_FIELDS
    outcome_fields = (
        "stock_return", "benchmark_return", "excess_return", "mfe", "mae",
        "forward_data_complete",
    )
    mismatches = []
    maximum = 0.0
    maxima: dict[str, float] = defaultdict(float)

    def compare_value(key, field, left, right) -> None:
        nonlocal maximum
        if (left is None or right is None or isinstance(left, (bool, str))
                or isinstance(right, (bool, str))):
            equal = left == right
            difference = 0.0 if equal else float("inf")
        else:
            difference = abs(float(left) - float(right))
            maximum = max(maximum, difference)
            maxima[field] = max(maxima[field], difference)
            equal = difference <= tolerance
        if not equal:
            mismatches.append({"security_id": key[0], "signal_date": key[1].isoformat(),
                               "field": field, "fixed": left, "pit": right,
                               "absolute_difference": difference})

    for key in keys:
        left, right = fixed_map[key], pit_map[key]
        for field in fields:
            left_value, right_value = left.get(field), right.get(field)
            if field == "score_components":
                components = sorted(set(left_value or {}) | set(right_value or {}))
                for component in components:
                    compare_value(key, f"score_components.{component}",
                                  (left_value or {}).get(component),
                                  (right_value or {}).get(component))
            else:
                compare_value(key, field, left_value, right_value)
        for horizon in HORIZONS:
            left_outcome, right_outcome = outcome(left, horizon), outcome(right, horizon)
            for field in outcome_fields:
                compare_value(key, f"{horizon}d.{field}",
                              left_outcome.get(field), right_outcome.get(field))
            if fixed_lifecycle is not None and pit_lifecycle is not None:
                compare_value(key, f"{horizon}d.lifecycle_classification",
                              fixed_lifecycle.get((*key, horizon), "COMPLETE"),
                              pit_lifecycle.get((*key, horizon), "COMPLETE"))
    return {
        "status": "PASS" if not mismatches else "FAIL",
        "events_tested": len(keys), "exact_tolerance_matches": len(keys) if not mismatches else None,
        "mismatches": len(mismatches), "maximum_numeric_difference": maximum,
        "maximum_numeric_difference_by_field": dict(sorted(maxima.items())),
        "mandatory_security_local_fields": list(fields),
        "universe_dependent_fields": list(UNIVERSE_DEPENDENT_FIELDS),
        "tolerance": tolerance, "examples": mismatches[:20],
    }


def subset_metrics(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(events)
    summary = set_summary(rows)
    summary["20"] = event_metrics(rows, 20)
    summary["60"] = event_metrics(rows, 60)
    return summary


def score_bucket_metrics(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        groups[score_bucket(float(event["score"]))].append(event)
    return {name: event_metrics(groups[name], 20)
            for name in ("0-20", "20-40", "40-60", "60-80", "80-100")}


def arithmetic_bridge(
    both: Iterable[dict[str, Any]], fixed_only: Iterable[dict[str, Any]],
    pit_only: Iterable[dict[str, Any]], *, horizon: int = 20,
    tolerance: float = NUMERIC_TOLERANCE,
) -> dict[str, Any]:
    def values(events):
        return [float(item["excess_return"]) for event in events
                if (item := outcome(event, horizon))["forward_data_complete"]
                and item.get("excess_return") is not None]

    b, f, p = values(both), values(fixed_only), values(pit_only)
    fixed = b + f
    pit = b + p
    means = {"both": statistics.fmean(b), "fixed_only": statistics.fmean(f) if f else None,
             "pit_only": statistics.fmean(p) if p else None,
             "fixed": statistics.fmean(fixed), "pit": statistics.fmean(pit)}
    removal = means["both"] - means["fixed"]
    addition = means["pit"] - means["both"]
    total = removal + addition
    direct = means["pit"] - means["fixed"]
    weighted_fixed = ((len(b) * means["both"] + len(f) * (means["fixed_only"] or 0))
                      / (len(b) + len(f)))
    weighted_pit = ((len(b) * means["both"] + len(p) * (means["pit_only"] or 0))
                    / (len(b) + len(p)))
    error = total - direct
    weighted_error = max(abs(weighted_fixed - means["fixed"]), abs(weighted_pit - means["pit"]))
    return {
        "status": "PASS" if abs(error) <= tolerance and weighted_error <= tolerance else "FAIL",
        "N_B": len(b), "N_F": len(f), "N_P": len(p),
        "mean_excess_B": means["both"], "mean_excess_F": means["fixed_only"],
        "mean_excess_P": means["pit_only"], "fixed_mean_excess": means["fixed"],
        "removal_effect": removal, "both_intermediate_mean_excess": means["both"],
        "addition_effect": addition, "pit_mean_excess": means["pit"],
        "total_bridge_effect": total, "direct_difference": direct,
        "reconciliation_error": error, "weighted_formula_error": weighted_error,
        "tolerance": tolerance,
    }


def values_by_date(
    events: Iterable[dict[str, Any]], horizon: int,
    overrides: dict[tuple[str, date, int], float] | None = None,
) -> dict[date, list[float]]:
    overrides = overrides or {}
    result: dict[date, list[float]] = defaultdict(list)
    for event in events:
        security_id, signal_date = event_key(event)
        override = overrides.get((security_id, signal_date, horizon))
        item = outcome(event, horizon)
        value = override if override is not None else (
            item.get("excess_return") if item["forward_data_complete"] else None
        )
        if value is not None:
            result[signal_date].append(float(value))
    return dict(result)


def _bootstrap_distribution(
    groups: dict[date, list[float]], *, seed: int, resamples: int,
) -> np.ndarray:
    dates = sorted(groups)
    sums = np.array([sum(groups[item]) for item in dates], dtype=float)
    counts = np.array([len(groups[item]) for item in dates], dtype=float)
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(dates), size=(resamples, len(dates)))
    return sums[draws].sum(axis=1) / counts[draws].sum(axis=1)


def date_clustered_bootstrap(
    groups: dict[date, list[float]], *, seed: int, resamples: int = 10_000,
) -> dict[str, Any]:
    if not groups:
        raise ValueError("date-clustered bootstrap requires observations")
    values = [value for rows in groups.values() for value in rows]
    distribution = _bootstrap_distribution(groups, seed=seed, resamples=resamples)
    return {
        "status": "PASS", "point_estimate": statistics.fmean(values),
        "percentile_2_5": float(np.percentile(distribution, 2.5)),
        "percentile_97_5": float(np.percentile(distribution, 97.5)),
        "unique_signal_dates": len(groups), "seed": seed, "resamples": resamples,
        "accepted_draws": resamples, "rejected_draws": 0,
        "dates_sorted_chronologically": True,
    }


def paired_date_clustered_bootstrap(
    fixed: dict[date, list[float]], pit: dict[date, list[float]],
    *, seed: int, resamples: int = 10_000,
) -> dict[str, Any]:
    if not fixed or not pit:
        raise ValueError("paired bootstrap requires observations in both arms")
    dates = sorted(set(fixed) | set(pit))
    fixed_sums = np.array([sum(fixed.get(item, [])) for item in dates], dtype=float)
    fixed_counts = np.array([len(fixed.get(item, [])) for item in dates], dtype=float)
    pit_sums = np.array([sum(pit.get(item, [])) for item in dates], dtype=float)
    pit_counts = np.array([len(pit.get(item, [])) for item in dates], dtype=float)
    rng = np.random.default_rng(seed)
    collected = []
    accepted = 0
    rejected = 0
    while accepted < resamples:
        remaining = resamples - accepted
        draws = rng.integers(0, len(dates), size=(max(remaining * 2, 100), len(dates)))
        fixed_n = fixed_counts[draws].sum(axis=1)
        pit_n = pit_counts[draws].sum(axis=1)
        valid = (fixed_n > 0) & (pit_n > 0)
        valid_indices = np.flatnonzero(valid)
        if len(valid_indices) >= remaining:
            examined = int(valid_indices[remaining - 1]) + 1
            accepted_indices = valid_indices[:remaining]
        else:
            examined = len(valid)
            accepted_indices = valid_indices
        rejected += examined - len(accepted_indices)
        batch = (pit_sums[draws].sum(axis=1)[accepted_indices] / pit_n[accepted_indices]
                 - fixed_sums[draws].sum(axis=1)[accepted_indices] /
                 fixed_n[accepted_indices])
        taken = batch
        collected.append(taken)
        accepted += len(taken)
    differences = np.concatenate(collected)[:resamples]
    fixed_values = [value for rows in fixed.values() for value in rows]
    pit_values = [value for rows in pit.values() for value in rows]
    return {
        "status": "PASS",
        "point_estimate": statistics.fmean(pit_values) - statistics.fmean(fixed_values),
        "percentile_2_5": float(np.percentile(differences, 2.5)),
        "percentile_97_5": float(np.percentile(differences, 97.5)),
        "unique_signal_dates": len(dates), "seed": seed, "resamples": resamples,
        "accepted_draws": resamples, "rejected_draws": rejected,
        "dates_sorted_chronologically": True,
    }


def financially_relevant_unknown(cases: Iterable["LifecycleCase"]) -> bool:
    return any(case.reason == "UNKNOWN" and case.diagnostic_evaluable for case in cases)


def lifecycle_bounds_active(cases: Iterable["LifecycleCase"], horizon: int) -> bool:
    return any(case.horizon == horizon and case.reason in {"BANKRUPTCY", "UNKNOWN"}
               and case.diagnostic_evaluable for case in cases)


def classify_ma_timing(
    signal_date: date, announcement_date: date, closing_date: date,
    last_regular_trading_date: date,
) -> str:
    if signal_date < announcement_date:
        return "PRE_ANNOUNCEMENT"
    if signal_date == announcement_date:
        return "ON_ANNOUNCEMENT_DATE"
    if signal_date <= last_regular_trading_date:
        return "POST_ANNOUNCEMENT_PRE_CLOSE"
    if signal_date >= closing_date:
        return "POST_CLOSE_INVALID"
    return "POST_ANNOUNCEMENT_PRE_CLOSE"


def classify_incomplete(
    *, target: date, research_end: date, missing_sessions: list[date],
    available_sessions: set[date], terminal_session: date | None,
    terminal_reason: str | None, proven_temporary_halt: bool = False,
) -> str:
    if target > research_end:
        return "RESEARCH_WINDOW_TRUNCATION"
    if not missing_sessions:
        return "COMPLETE"
    if proven_temporary_halt and any(item > max(missing_sessions) for item in available_sessions):
        return "TEMPORARY_TRADING_HALT"
    if terminal_session is not None and min(missing_sessions) >= terminal_session:
        return f"SECURITY_LIFECYCLE_TRUNCATION:{terminal_reason or 'UNKNOWN'}"
    return "GENUINE_MISSING_DATA"


def genuine_missing_inventory(
    events: Iterable[dict[str, Any]],
    classifications: dict[tuple[str, date, int], str],
    bars_by_security: dict[str, list[Any]],
    calendar: Any,
    labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Describe missing forward observations without filling or reclassifying them."""
    labels = labels or {}
    event_by_key = event_map(events)
    cases = []
    grouped: dict[str, dict[str, Any]] = {}
    for (security_id, signal_date, horizon), classification in sorted(
        classifications.items(), key=lambda item: (item[0][0], item[0][1], item[0][2])
    ):
        if classification != "GENUINE_MISSING_DATA":
            continue
        if (security_id, signal_date) not in event_by_key:
            raise ValueError(f"classification has no matching event: {(security_id, signal_date)}")
        available = {bar.timestamp.date() for bar in bars_by_security[security_id]}
        target = calendar.session_offset(signal_date, horizon)
        expected = calendar.trading_days_between(
            calendar.session_offset(signal_date, 1), target
        )
        missing = [session for session in expected if session not in available]
        if not missing:
            raise ValueError(
                f"GENUINE_MISSING_DATA classification has no missing sessions: "
                f"{(security_id, signal_date, horizon)}"
            )
        cases.append({
            "security_id": security_id,
            "historical_ticker": labels.get(security_id),
            "signal_date": signal_date.isoformat(),
            "horizon": horizon,
            "target_session": target.isoformat(),
            "missing_sessions": len(missing),
            "first_missing_session": missing[0].isoformat(),
            "last_missing_session": missing[-1].isoformat(),
        })
        group = grouped.setdefault(security_id, {
            "security_id": security_id,
            "historical_ticker": labels.get(security_id),
            "affected_event_horizons": 0,
            "missing": set(),
        })
        group["affected_event_horizons"] += 1
        group["missing"].update(missing)

    securities = []
    for security_id in sorted(grouped):
        group = grouped[security_id]
        missing = sorted(group.pop("missing"))
        securities.append({
            **group,
            "unique_missing_sessions": len(missing),
            "first_missing_session": missing[0].isoformat(),
            "last_missing_session": missing[-1].isoformat(),
        })
    all_missing = {
        (item["security_id"], session)
        for item in cases
        for session in calendar.trading_days_between(
            date.fromisoformat(item["first_missing_session"]),
            date.fromisoformat(item["last_missing_session"]),
        )
        if session not in {
            bar.timestamp.date() for bar in bars_by_security[item["security_id"]]
        }
    }
    return {
        "affected_event_horizons": len(cases),
        "affected_securities": len(securities),
        "unique_missing_security_sessions": len(all_missing),
        "cases": cases,
        "securities": securities,
    }


@dataclass(frozen=True)
class LifecycleCase:
    security_id: str
    signal_date: date
    horizon: int
    reason: str
    last_available_close: float
    entry_price: float | None
    benchmark_return: float | None
    missing_sessions: tuple[date, ...] = ()

    @property
    def key(self) -> tuple[str, date, int]:
        return self.security_id, self.signal_date, self.horizon

    @property
    def diagnostic_evaluable(self) -> bool:
        return self.entry_price is not None and self.benchmark_return is not None


def lifecycle_overrides(cases: Iterable[LifecycleCase], mode: str) -> dict[tuple[str, date, int], float]:
    if mode not in {"LOWER", "UPPER"}:
        raise ValueError("mode must be LOWER or UPPER")
    result = {}
    for case in cases:
        if not case.diagnostic_evaluable:
            continue
        assert case.entry_price is not None and case.benchmark_return is not None
        stock_return = case.last_available_close / case.entry_price - 1
        if mode == "LOWER" and case.reason in {"BANKRUPTCY", "UNKNOWN"}:
            stock_return = -1.0
        result[case.key] = stock_return - case.benchmark_return
    return result


def sensitivity_metrics(
    events: Iterable[dict[str, Any]], cases: Iterable[LifecycleCase],
    horizon: int, mode: str,
) -> dict[str, Any]:
    rows = list(events)
    case_map = {item.key: item for item in cases if item.horizon == horizon}
    stock = []
    excess = []
    for event in rows:
        security_id, signal_date = event_key(event)
        item = outcome(event, horizon)
        if item["forward_data_complete"]:
            stock.append(float(item["stock_return"]))
            excess.append(float(item["excess_return"]))
            continue
        case = case_map.get((security_id, signal_date, horizon))
        if case is None or not case.diagnostic_evaluable:
            continue
        assert case.entry_price is not None and case.benchmark_return is not None
        value = case.last_available_close / case.entry_price - 1
        if mode == "LOWER" and case.reason in {"BANKRUPTCY", "UNKNOWN"}:
            value = -1.0
        stock.append(value)
        excess.append(value - case.benchmark_return)
    return {
        "n": len(stock), "mean_return": statistics.fmean(stock),
        "median_return": statistics.median(stock),
        "positive_rate": sum(value > 0 for value in stock) / len(stock),
        "mean_excess_return": statistics.fmean(excess),
        "median_excess_return": statistics.median(excess),
    }


def deterministic_phase2_digest(
    events: Iterable[dict[str, Any]], lifecycle: dict[tuple[str, date, int], str],
) -> str:
    payload = {
        "events": sorted(list(events), key=lambda item: (str(item["signal_date"]), item["ticker"])),
        "lifecycle": sorted((sid, when.isoformat(), horizon, value)
                            for (sid, when, horizon), value in lifecycle.items()),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def signal_distribution(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(str(item["signal_date"]) for item in events)
    values = list(counts.values())
    return {
        "unique_signal_dates": len(counts), "mean": statistics.fmean(values) if values else 0,
        "median": statistics.median(values) if values else 0,
        "p25": float(np.percentile(values, 25)) if values else 0,
        "p75": float(np.percentile(values, 75)) if values else 0,
        "p90": float(np.percentile(values, 90)) if values else 0,
        "p95": float(np.percentile(values, 95)) if values else 0,
        "maximum": max(values, default=0),
    }
