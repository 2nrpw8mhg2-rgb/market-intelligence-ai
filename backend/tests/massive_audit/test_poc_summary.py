from app.cli.run_massive_second_source_poc import decide, identifiers_match, summarize, target_groups


def test_target_groups_select_only_declared_poc3_gaps() -> None:
    master = [
        {"membership": {"ticker": "A"},
         "identity": {"confidence": "UNRESOLVED", "reuse_status": "NONE"},
         "event": {"confidence": "HIGH"}},
        {"membership": {"ticker": "B"},
         "identity": {"confidence": "HIGH", "reuse_status": "TICKER_REUSE_CONFIRMED"},
         "event": {"confidence": "LOW"}},
    ]

    assert target_groups(master) == {
        "unresolved": {"A"}, "reuse": {"B"}, "low_terminal": {"B"},
    }


def test_identifier_match_normalizes_cik_and_accepts_figi() -> None:
    assert identifiers_match({"CIK": "000123"}, {"cik": "123"})
    assert identifiers_match({"OpenFigi": "BBG1"}, {"composite_figi": "BBG1"})
    assert not identifiers_match({"CIK": "123"}, {"cik": "456"})


def test_decision_requires_more_than_partial_identity_evidence() -> None:
    summary = {
        "unresolved_identity_resolved": 5,
        "unresolved_identity_total": 21,
        "ticker_change_evidence": 9,
        "structured_acquisition_terms": 0,
        "structured_bankruptcy_recoveries": 0,
    }
    assert decide(summary) == "MASSIVE_PARTIALLY_SUFFICIENT"


def test_summary_excludes_non_evaluable_price_horizons() -> None:
    record = {
        "ticker": "OLD", "groups": ["low_terminal"],
        "resolution": {"identity_resolved": False, "ticker_change_events": 0,
                       "delisted_date_available": False},
        "massive": {"details": {}, "post_removal": {str(h): None for h in (1, 5, 10, 20, 60)}},
        "eodhd": {"event": {"classification": "DELISTING"}},
    }
    summary = summarize([record], {"unresolved": set(), "reuse": set(), "low_terminal": {"OLD"}})
    assert summary["post_removal_low_terminal"]["1"] == {
        "eligible": 0, "complete": 0, "coverage_pct": None,
    }
