from datetime import date

import pytest

from app.research.fixed_rebuilt import score_bucket
from app.research.pit_phase2 import (
    LifecycleCase, arithmetic_bridge, classify_incomplete, compare_both_invariance,
    date_clustered_bootstrap, decompose_events, deterministic_phase2_digest,
    genuine_missing_inventory, lifecycle_overrides, paired_date_clustered_bootstrap,
    sensitivity_metrics,
)


def event(security_id: str, when: str, excess: float = .1, stock: float = .2,
          score: float = 50) -> dict:
    return {
        "ticker": security_id, "signal_date": when, "close": 100,
        "entry_price": 101, "relative_volume": 2, "score": score,
        "outcomes": [{
            "horizon": horizon, "stock_return": stock,
            "benchmark_return": stock - excess, "excess_return": excess,
            "mfe": .3 if horizon > 1 else None, "mae": -.1 if horizon > 1 else None,
            "forward_data_complete": True,
        } for horizon in (1, 5, 10, 20, 60)],
    }


def test_security_id_and_signal_date_define_event_decomposition() -> None:
    fixed = [event("security-a", "2024-01-02"), event("fixed-only", "2024-01-03")]
    pit = [event("security-a", "2024-01-02"), event("pit-only", "2024-01-04")]
    result = decompose_events(fixed, pit)
    assert [item["ticker"] for item in result["BOTH_FIXED"]] == ["security-a"]
    assert [item["ticker"] for item in result["FIXED_ONLY"]] == ["fixed-only"]
    assert [item["ticker"] for item in result["PIT_ONLY"]] == ["pit-only"]


def test_both_invariance_checks_all_financial_fields_and_lifecycle() -> None:
    fixed = [event("security-a", "2024-01-02")]
    pit = [event("security-a", "2024-01-02")]
    lifecycle = {("security-a", date(2024, 1, 2), 20): "COMPLETE"}
    result = compare_both_invariance(fixed, pit, lifecycle, lifecycle)
    assert result["status"] == "PASS"
    assert result["events_tested"] == 1
    pit[0]["outcomes"][3]["stock_return"] += 1e-5
    assert compare_both_invariance(fixed, pit)["status"] == "FAIL"


def test_arithmetic_bridge_reconciles_exact_count_weighted_difference() -> None:
    result = arithmetic_bridge(
        [event("both", "2024-01-02", .1)],
        [event("fixed", "2024-01-03", -.1)],
        [event("pit", "2024-01-04", .3)],
    )
    assert result["status"] == "PASS"
    assert result["fixed_mean_excess"] == pytest.approx(0)
    assert result["pit_mean_excess"] == pytest.approx(.2)
    assert result["total_bridge_effect"] == pytest.approx(.2)


def test_incomplete_classification_separates_window_lifecycle_and_resumed_halt() -> None:
    missing = [date(2024, 1, 3)]
    assert classify_incomplete(
        target=date(2024, 2, 1), research_end=date(2024, 1, 31),
        missing_sessions=missing, available_sessions=set(), terminal_session=None,
        terminal_reason=None,
    ) == "RESEARCH_WINDOW_TRUNCATION"
    assert classify_incomplete(
        target=date(2024, 1, 5), research_end=date(2024, 1, 31),
        missing_sessions=missing, available_sessions={date(2024, 1, 4)},
        terminal_session=None, terminal_reason=None, proven_temporary_halt=True,
    ) == "TEMPORARY_TRADING_HALT"
    assert classify_incomplete(
        target=date(2024, 1, 5), research_end=date(2024, 1, 31),
        missing_sessions=missing, available_sessions=set(),
        terminal_session=date(2024, 1, 3), terminal_reason="ACQUISITION",
    ) == "SECURITY_LIFECYCLE_TRUNCATION:ACQUISITION"


def test_lower_bound_uses_minus_100_for_bankruptcy_and_unknown_only() -> None:
    cases = [
        LifecycleCase("bankrupt", date(2024, 1, 2), 20, "BANKRUPTCY", 60, 100, .05),
        LifecycleCase("unknown", date(2024, 1, 2), 20, "UNKNOWN", 70, 100, .05),
        LifecycleCase("acquired", date(2024, 1, 2), 20, "ACQUISITION", 120, 100, .05),
        LifecycleCase("merged", date(2024, 1, 2), 20, "MERGER", 110, 100, .05),
    ]
    lower = lifecycle_overrides(cases, "LOWER")
    upper = lifecycle_overrides(cases, "UPPER")
    assert lower[cases[0].key] == pytest.approx(-1.05)
    assert lower[cases[1].key] == pytest.approx(-1.05)
    assert lower[cases[2].key] == pytest.approx(.15)
    assert lower[cases[3].key] == pytest.approx(.05)
    assert upper[cases[0].key] == pytest.approx(-.45)


def test_lifecycle_case_without_next_open_is_audit_only() -> None:
    case = LifecycleCase(
        "acquired", date(2024, 1, 2), 20, "ACQUISITION", 100, None, None
    )
    assert not case.diagnostic_evaluable
    assert lifecycle_overrides([case], "LOWER") == {}
    assert lifecycle_overrides([case], "UPPER") == {}


def test_sensitivity_adds_only_lifecycle_cases_not_window_truncation() -> None:
    incomplete = event("bankrupt", "2024-01-02")
    incomplete["outcomes"][3].update({"stock_return": None, "excess_return": None,
                                       "forward_data_complete": False})
    case = LifecycleCase("bankrupt", date(2024, 1, 2), 20, "BANKRUPTCY", 60, 100, .05)
    result = sensitivity_metrics([incomplete], [case], 20, "LOWER")
    assert result["n"] == 1
    assert result["mean_return"] == -1


def test_date_clustered_bootstrap_is_seeded_and_keeps_date_clusters() -> None:
    groups = {date(2024, 1, 2): [.1, .2], date(2024, 1, 3): [-.1]}
    first = date_clustered_bootstrap(groups, seed=20260929, resamples=500)
    second = date_clustered_bootstrap(groups, seed=20260929, resamples=500)
    assert first == second
    assert first["unique_signal_dates"] == 2
    assert first["point_estimate"] == pytest.approx((.1 + .2 - .1) / 3)


def test_paired_bootstrap_uses_aligned_union_of_dates_and_fixed_seed() -> None:
    fixed = {date(2024, 1, 2): [.1], date(2024, 1, 3): [.2]}
    pit = {date(2024, 1, 2): [.3], date(2024, 1, 4): [.4]}
    first = paired_date_clustered_bootstrap(fixed, pit, seed=7, resamples=500)
    second = paired_date_clustered_bootstrap(fixed, pit, seed=7, resamples=500)
    assert first == second
    assert first["unique_signal_dates"] == 3
    assert first["point_estimate"] == pytest.approx(.2)


def test_score_boundaries_and_phase2_digest_are_deterministic() -> None:
    assert [score_bucket(value) for value in (20, 40, 60, 80)] == [
        "20-40", "40-60", "60-80", "80-100"
    ]
    events = [event("b", "2024-01-03"), event("a", "2024-01-02")]
    lifecycle = {("a", date(2024, 1, 2), 20): "COMPLETE"}
    assert deterministic_phase2_digest(events, lifecycle) == deterministic_phase2_digest(
        reversed(events), lifecycle
    )


def test_genuine_missing_inventory_deduplicates_security_sessions() -> None:
    class Bar:
        def __init__(self, when: date) -> None:
            from datetime import datetime
            self.timestamp = datetime.combine(when, datetime.min.time())

    class Calendar:
        sessions = [date(2024, 1, day) for day in (2, 3, 4, 5, 8)]

        def session_offset(self, when: date, offset: int) -> date:
            return self.sessions[self.sessions.index(when) + offset]

        def trading_days_between(self, start: date, end: date) -> list[date]:
            return [item for item in self.sessions if start <= item <= end]

    events = [event("security-a", "2024-01-02")]
    classifications = {
        ("security-a", date(2024, 1, 2), 1): "GENUINE_MISSING_DATA",
        ("security-a", date(2024, 1, 2), 5): "COMPLETE",
    }
    inventory = genuine_missing_inventory(
        events, classifications, {"security-a": [Bar(date(2024, 1, 2))]},
        Calendar(), {"security-a": "OLD"},
    )
    assert inventory["affected_event_horizons"] == 1
    assert inventory["affected_securities"] == 1
    assert inventory["unique_missing_security_sessions"] == 1
    assert inventory["securities"][0]["historical_ticker"] == "OLD"
