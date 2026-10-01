import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from app.research.pit_phase2a import detect_signals_only
from app.research.pit_phase2b import (
    STRATEGY_PRIOR_OBSERVATIONS, classify_pre_membership_history,
    exact_strategy_warmup, membership_allows_signal,
    prove_non_blocking_documentation_gap, split_symmetric_history,
    validate_boundary_evidence,
)
from app.schemas.market_data import MarketBar
from app.schemas.scanner import BreakoutStrategyParameters


def sessions(start: date, count: int) -> list[date]:
    return [start + timedelta(days=index) for index in range(count)]


def listing_evidence() -> dict:
    return {
        "new-security": {
            "event_type": "SPINOFF",
            "first_legitimate_trading_date": "2024-01-02",
            "confidence": "HIGH",
            "sources": [{"url": "https://www.sec.gov/example"}],
        }
    }


def test_exact_warmup_is_199_prior_not_an_arbitrary_220() -> None:
    result = exact_strategy_warmup()
    assert result["total_observations_through_evaluation_session"] == 200
    assert result["strictly_prior_observations"] == 199
    assert result["binding_feature"] == "SMA_200"


def test_sufficient_pre_membership_history_uses_legitimate_bars_before_entry() -> None:
    valid_from = date(2024, 8, 1)
    result = classify_pre_membership_history(
        security_id="old-security", valid_from=valid_from,
        logical_bar_dates=sessions(date(2024, 1, 1), 213), listing_evidence={},
    )
    assert result["classification"] == "SUFFICIENT_PRE_MEMBERSHIP_HISTORY"
    assert result["legitimate_observations_before_valid_from"] >= STRATEGY_PRIOR_OBSERVATIONS
    assert result["full_warmup_at_valid_from"] is True


def test_natural_short_history_requires_authoritative_listing_evidence() -> None:
    result = classify_pre_membership_history(
        security_id="new-security", valid_from=date(2024, 1, 10),
        logical_bar_dates=sessions(date(2024, 1, 2), 8),
        listing_evidence=listing_evidence(),
    )
    assert result["classification"] == "NATURAL_SHORT_PREHISTORY_EVIDENCED"
    assert result["full_warmup_at_valid_from"] is False


def test_missing_expected_prehistory_fails_closed() -> None:
    result = classify_pre_membership_history(
        security_id="established-security", valid_from=date(2024, 2, 1),
        logical_bar_dates=sessions(date(2024, 1, 1), 20), listing_evidence={},
    )
    assert result["classification"] == "INSUFFICIENT_PRE_MEMBERSHIP_HISTORY"


def test_identity_invalid_history_is_not_counted_as_warmup() -> None:
    result = classify_pre_membership_history(
        security_id="new-security", valid_from=date(2024, 1, 10),
        logical_bar_dates=sessions(date(2000, 1, 1), 500),
        listing_evidence=listing_evidence(), logical_history_identity_valid=False,
    )
    assert result["classification"] == "NATURAL_SHORT_PREHISTORY_EVIDENCED"
    assert result["legitimate_observations_before_valid_from"] == 0
    assert result["first_logical_bar_currently_available"] is None


def test_membership_boundaries_control_signals_only_with_half_open_semantics() -> None:
    start, end = date(2024, 1, 3), date(2024, 1, 5)
    assert membership_allows_signal(date(2024, 1, 2), start, end) is False
    assert membership_allows_signal(start, start, end) is True
    assert membership_allows_signal(date(2024, 1, 4), start, end) is True
    assert membership_allows_signal(end, start, end) is False


def test_symmetric_history_preserves_pre_and_post_membership_bars() -> None:
    dates = sessions(date(2024, 1, 1), 7)
    result = split_symmetric_history(
        dates, valid_from=date(2024, 1, 3), valid_to=date(2024, 1, 6)
    )
    assert result["PRE_MEMBERSHIP_HISTORY"] == dates[:2]
    assert result["MEMBERSHIP_ELIGIBILITY"] == dates[2:5]
    assert result["POST_MEMBERSHIP_FORWARD_HISTORY"] == dates[5:]
    assert sum(map(len, result.values())) == len(dates)


def test_real_signal_path_uses_prehistory_but_never_signals_outside_membership() -> None:
    class Calendar:
        @staticmethod
        def session_offset(when: date, offset: int) -> date:
            return when + timedelta(days=offset)

    start = date(2023, 1, 1)
    bars = []
    for index in range(205):
        when = start + timedelta(days=index)
        close = 10 + index * 0.1
        volume = 2_000_000 if index in {199, 200, 201, 202} else 1_000_000
        bars.append(MarketBar(
            ticker="AAA", timestamp=datetime.combine(when, datetime.min.time(), UTC),
            open=close, high=close + 0.01, low=close - 0.01, close=close, volume=volume,
        ))
    valid_from, valid_to = bars[200].timestamp.date(), bars[202].timestamp.date()
    result = detect_signals_only(
        {"security-a": bars}, BreakoutStrategyParameters(min_avg_dollar_volume=1),
        start=bars[199].timestamp.date(), end=bars[202].timestamp.date(),
        is_member=lambda _security_id, when: membership_allows_signal(
            when, valid_from, valid_to
        ),
        calendar=Calendar(),
    )
    assert [item["signal_date"] for item in result] == [
        valid_from.isoformat(), bars[201].timestamp.date().isoformat(),
    ]


def test_nonblocking_gap_requires_zero_signals_and_full_research_invariance() -> None:
    evidence = {
        "security-a": {
            "unresolved_fact": "OTC legal continuity",
            "authoritative_evidence_unavailable_reason": "No conclusive cached identifier link",
            "research_invariance_reason": "No eligible signal precedes termination",
        }
    }
    result = prove_non_blocking_documentation_gap(
        security_id="security-a", signal_dates=[], feature_history_complete=True,
        next_open_invariant=True, forward_horizons_invariant=True, evidence=evidence,
    )
    assert result["classification"] == "NON_BLOCKING_DOCUMENTATION_GAP"
    blocked = prove_non_blocking_documentation_gap(
        security_id="security-a", signal_dates=[date(2024, 1, 2)],
        feature_history_complete=True, next_open_invariant=True,
        forward_horizons_invariant=True, evidence=evidence,
    )
    assert blocked["classification"] == "BLOCKING_RESEARCH_GAP"


def test_repository_boundary_evidence_is_auditable() -> None:
    path = Path(__file__).parents[2] / "docs" / "PIT_PHASE2B_BOUNDARY_EVIDENCE.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    validate_boundary_evidence(payload)
    assert len(payload["listing_events"]) >= 24
    assert len(payload["lifecycle_events"]) >= 28
    assert {item["ticker"] for item in payload["documentation_gaps"].values()} == {
        "FRC", "GPS", "RAL_OLD",
    }
