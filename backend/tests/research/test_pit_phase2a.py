import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from app.research.pit_phase2a import (
    build_mna_signal_ledger, build_systemic_inventory,
    classify_next_open_executability, classify_observation_gap,
    classify_signal_timing, reconcile_forward_cases,
    validate_lifecycle_evidence,
)
from app.schemas.market_data import MarketBar


class Calendar:
    def trading_days_between(self, start: date, end: date) -> list[date]:
        return [start + timedelta(days=index) for index in range((end - start).days + 1)
                if (start + timedelta(days=index)).weekday() < 5]

    def session_offset(self, when: date, offset: int) -> date:
        cursor = when
        direction = 1 if offset >= 0 else -1
        for _ in range(abs(offset)):
            cursor += timedelta(days=direction)
            while cursor.weekday() >= 5:
                cursor += timedelta(days=direction)
        return cursor


def bar(when: date, *, ticker: str = "OLD", close: float = 10) -> MarketBar:
    return MarketBar(
        ticker=ticker, timestamp=datetime.combine(when, datetime.min.time(), UTC),
        open=close, high=close + 1, low=close - 1, close=close, volume=1_000_000,
    )


def evidence(reason: str = "ACQUISITION") -> dict:
    return {
        "security-a": {
            "classification": reason, "confidence": "HIGH",
            "last_regular_trading_date": "2024-01-05", "closing_date": "2024-01-06",
            "announcement_date": "2023-12-01", "transaction_type": "CASH",
            "sources": [{"url": "https://www.sec.gov/example"}],
        }
    }


def test_lifecycle_evidence_requires_supported_reason_chronology_and_source() -> None:
    validate_lifecycle_evidence(evidence())
    invalid = evidence("UNKNOWN")
    try:
        validate_lifecycle_evidence(invalid)
    except ValueError as exc:
        assert "unsupported lifecycle" in str(exc)
    else:
        raise AssertionError("unsupported lifecycle evidence must fail closed")


def test_acquisition_and_merger_classifications_reconcile_post_termination_only() -> None:
    cases = [{
        "security_id": "security-a", "signal_date": "2024-01-04", "horizon": 5,
        "first_missing_session": "2024-01-08", "last_missing_session": "2024-01-10",
        "missing_sessions": 3, "target_session": "2024-01-10",
    }]
    for reason in ("ACQUISITION", "MERGER"):
        result = reconcile_forward_cases(cases, evidence(reason), Calendar())
        assert result["counts"]["SECURITY_LIFECYCLE_TRUNCATION"] == 3
        assert result["counts"]["GENUINE_MISSING_DATA"] == 0
        assert result["reconciled_total"] == 3


def test_reconciliation_fails_closed_without_evidence() -> None:
    case = [{
        "security_id": "security-a", "signal_date": "2024-01-04", "horizon": 1,
        "first_missing_session": "2024-01-08", "last_missing_session": "2024-01-08",
        "missing_sessions": 1, "target_session": "2024-01-08",
    }]
    result = reconcile_forward_cases(case, {}, Calendar())
    assert result["counts"]["UNKNOWN"] == 1


def test_provider_gap_requires_proven_identity_and_valid_real_bars() -> None:
    expected = [date(2024, 1, 2), date(2024, 1, 3)]
    primary = [bar(expected[0])]
    alternative = [bar(expected[1])]
    assert classify_observation_gap(
        expected_sessions=expected, primary_bars=primary,
        alternative_bars=alternative, identity_proven=True,
    ) == "PROVIDER_GAP_RESOLVED"
    assert classify_observation_gap(
        expected_sessions=expected, primary_bars=primary,
        alternative_bars=alternative, identity_proven=False,
    ) == "GENUINE_MISSING_DATA"


def test_temporary_halt_requires_subsequent_same_security_trading() -> None:
    expected = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)]
    primary = [bar(expected[0]), bar(expected[2])]
    assert classify_observation_gap(
        expected_sessions=expected, primary_bars=primary, alternative_bars=[],
        identity_proven=True, proven_temporary_halt=True,
    ) == "TEMPORARY_HALT"
    assert classify_observation_gap(
        expected_sessions=expected, primary_bars=primary[:1], alternative_bars=[],
        identity_proven=True, proven_temporary_halt=True,
    ) == "GENUINE_MISSING_DATA"


def test_gap_classification_does_not_mutate_or_synthesize_bars() -> None:
    primary = [bar(date(2024, 1, 2))]
    alternative = [bar(date(2024, 1, 3))]
    before = ([item.model_dump() for item in primary], [item.model_dump() for item in alternative])
    classify_observation_gap(
        expected_sessions=[date(2024, 1, 2), date(2024, 1, 3)],
        primary_bars=primary, alternative_bars=alternative, identity_proven=True,
    )
    assert before == ([item.model_dump() for item in primary],
                      [item.model_dump() for item in alternative])


def test_twtr_next_open_is_non_executable_only_when_lifecycle_precedes_next_session() -> None:
    assert classify_next_open_executability(
        signal_date=date(2022, 10, 27), next_expected_session=date(2022, 10, 28),
        available_sessions={date(2022, 10, 27)},
        last_regular_trading_date=date(2022, 10, 27),
    ) == "NON_EXECUTABLE_LIFECYCLE_TERMINATION"
    assert classify_next_open_executability(
        signal_date=date(2022, 10, 27), next_expected_session=date(2022, 10, 28),
        available_sessions={date(2022, 10, 27), date(2022, 10, 28)},
        last_regular_trading_date=date(2022, 10, 28),
    ) == "EXECUTABLE_WITH_COMPLETE_HORIZON"


def test_mna_timing_boundaries_and_post_close_invalid() -> None:
    announcement, last = date(2024, 1, 3), date(2024, 1, 5)
    assert classify_signal_timing(date(2024, 1, 2), announcement, last) == "PRE_ANNOUNCEMENT"
    assert classify_signal_timing(announcement, announcement, last) == "ON_ANNOUNCEMENT_DATE"
    assert classify_signal_timing(date(2024, 1, 4), announcement, last) == "POST_ANNOUNCEMENT_PRE_CLOSE"
    assert classify_signal_timing(date(2024, 1, 8), announcement, last) == "POST_CLOSE_INVALID"


def test_mna_ledger_preserves_security_identity_and_transaction_type() -> None:
    item = evidence()
    item["security-a"].update({
        "cash_consideration": "$10", "stock_consideration": None,
        "contingent_consideration": "non-transferable right",
        "non_tradable_component": True,
    })
    result = build_mna_signal_ledger(
        [{"security_id": "security-a", "signal_date": "2024-01-04"}], item,
        lambda security_id, when: "OLD" if security_id == "security-a" else None,
    )
    assert result["affected_securities"] == 1
    assert result["signal_counts"]["POST_ANNOUNCEMENT_PRE_CLOSE"] == 1
    assert result["transaction_counts"]["CASH"] == 1
    assert result["transactions_with_contingent_or_non_tradable_consideration"] == 1
    assert result["rows"][0]["ticker_at_signal_date"] == "OLD"


def test_systemic_inventory_keeps_unexplained_early_histories_visible() -> None:
    rows = [{
        "security_id": "security-a", "canonical_name": "Acquired Co",
        "membership": {"ticker": "AAA", "start": "2021-01-01", "end": "2024-01-08"},
        "prices": {"last": "2024-01-05"},
        "event": {"classification": "DELISTING", "confidence": "LOW"},
    }, {
        "security_id": "security-b", "canonical_name": "Unknown Co",
        "membership": {"ticker": "BBB", "start": "2021-01-01", "end": "2024-01-08"},
        "prices": {"last": "2024-01-05"},
        "event": {"classification": "INDEX_REMOVAL_STILL_TRADING", "confidence": "HIGH"},
    }]
    result = build_systemic_inventory(
        rows, {"security-a", "security-b"}, {}, {}, window_end=date(2024, 12, 31),
        calendar=Calendar(), gate_security_ids=set(),
    )
    assert result["counts"]["RECORDED_BUT_NOT_EVIDENCED"] == 1
    assert result["counts"]["UNCLASSIFIED_EARLY_PRICE_TERMINATION"] == 1
    assert result["status"] == "FAIL"


def test_repository_lifecycle_evidence_is_valid_and_contains_targeted_cases() -> None:
    path = Path(__file__).parents[2] / "docs" / "PIT_LIFECYCLE_EVIDENCE.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    validate_lifecycle_evidence(payload)
    assert {item["ticker"] for item in payload.values()} >= {
        "CERN", "NLSN", "WBA", "DAY", "CTRA", "EA", "TWTR",
    }
