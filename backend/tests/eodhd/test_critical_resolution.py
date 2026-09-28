from app.cli.run_eodhd_critical_resolution import decision, eod_quality, pit_status


def test_pre_window_exit_is_not_relevant_even_when_identity_is_unresolved() -> None:
    master = {
        "membership": {"end": "2020-01-01"},
        "event": {"confidence": "LOW", "post_removal_available": {"60": False}},
        "prices": {"coverage_pct": 0.0},
    }
    assert pit_status(master, True, True) == "NOT_RELEVANT_TO_TEST_WINDOW"


def test_in_window_unresolved_terminal_event_stays_critical() -> None:
    master = {
        "membership": {"end": "2024-01-01"},
        "event": {"confidence": "LOW", "post_removal_available": {"60": False}},
        "prices": {"coverage_pct": 100.0},
    }
    assert pit_status(master, False, False) == "STILL_CRITICAL"


def test_quality_flags_bad_rows_without_repairing_them() -> None:
    bars = [
        {"date": "2020-01-01", "open": 10, "high": 9, "low": 8, "close": 10, "adjusted_close": 10},
        {"date": "2020-01-01", "open": 1, "high": 1, "low": 0, "close": 1, "adjusted_close": .5},
    ]
    result = eod_quality(bars)
    assert result["duplicate_dates"] == 1
    assert result["impossible_ohlc"] == 1
    assert result["suspicious_zero_prices"] == 1
    assert result["adjustment_factor_changes"] == 1
    assert result["potential_adjustment_inconsistencies"] == ["2020-01-01"]


def test_decision_retains_exceptions_for_out_of_window_cases() -> None:
    assert decision([{"pit_status": "NOT_RELEVANT_TO_TEST_WINDOW"}]) == "EODHD_SUFFICIENT_WITH_EXCEPTIONS"
