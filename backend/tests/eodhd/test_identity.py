from datetime import date

import pytest

from app.eodhd.identity import (
    Confidence, LookaheadClass, MissingPriceCategory, ReuseStatus, SecurityAlias, StartDateStatus,
    TerminalEvent, build_symbol_change_graph, classify_lookahead_field, classify_missing_price,
    classify_null_start, classify_terminal_event, name_similarity, post_removal_availability,
    reuse_status, split_adjusted_signal_series, stable_security_id,
)
from app.eodhd.models import CorporateAction, EODBar, HistoricalConstituent


def membership(start=None, end=None):
    return HistoricalConstituent.model_validate({"Code": "ABC", "Name": "Alpha Beta Corporation",
        "StartDate": start, "EndDate": end, "IsActiveNow": int(end is None), "IsDelisted": 0})


def bar(day, close, volume=1_000):
    return EODBar(date=day, open=close, high=close, low=close, close=close,
                  adjusted_close=close, volume=volume)


def test_alias_validity_interval_boundaries_are_inclusive_and_explicit() -> None:
    alias = SecurityAlias(ticker="FB", exchange="US", valid_from=date(2012, 5, 18),
                          valid_to=date(2022, 6, 8), source="symbol_change", confidence=Confidence.HIGH)
    assert alias.valid_on(date(2022, 6, 8))
    assert not alias.valid_on(date(2022, 6, 9))


def test_ticker_reuse_requires_independent_name_evidence() -> None:
    assert reuse_status("Monsanto Company", "Monument Circle Acquisition Corp") is ReuseStatus.TICKER_REUSE_CONFIRMED
    assert reuse_status("Apple Inc", "Apple Incorporated") is ReuseStatus.NO_REUSE_EVIDENCE
    assert reuse_status("Unknown", None) is ReuseStatus.UNRESOLVED


def test_name_similarity_does_not_depend_on_company_suffixes() -> None:
    assert name_similarity("Apple Inc.", "Apple Incorporated") == 1


def test_null_start_is_classified_without_imputing_a_date() -> None:
    record = membership(start=None, end="2018-01-01")
    assert classify_null_start(record, date(2012, 4, 1)) is StartDateStatus.PRE_HISTORY_MEMBER
    assert record.start_date is None


def test_security_identity_is_stable_from_identifier_not_ticker() -> None:
    first = membership()
    renamed = first.model_copy(update={"code": "XYZ"})
    assert stable_security_id(first, {"ISIN": "US0000000001"}) == stable_security_id(
        renamed, {"ISIN": "US0000000001"},
    )


def test_end_date_hypotheses_remain_configurable() -> None:
    record = membership(start="2015-01-01", end="2020-01-02")
    assert record.is_member_on(date(2020, 1, 2), end_date_inclusive=True)
    assert not record.is_member_on(date(2020, 1, 2), end_date_inclusive=False)


def test_symbol_change_graph_finds_chains_and_cycles() -> None:
    graph = build_symbol_change_graph([
        {"old_symbol": "A", "new_symbol": "B"}, {"old_symbol": "B", "new_symbol": "C"},
        {"old_symbol": "X", "new_symbol": "Y"}, {"old_symbol": "Y", "new_symbol": "X"},
    ])
    assert ["A", "B", "C"] in graph["multi_hop_chains"]
    assert graph["cycles"]


def test_split_adjusted_signal_series_removes_forward_split_discontinuity() -> None:
    bars = [bar(date(2024, 6, 7), 1000), bar(date(2024, 6, 10), 102)]
    splits = [CorporateAction(date=date(2024, 6, 10), split="10/1")]
    adjusted = split_adjusted_signal_series(bars, splits)
    assert adjusted[0]["close"] == 100
    assert adjusted[1]["close"] == 102
    assert adjusted[1]["close"] / adjusted[0]["close"] - 1 == pytest.approx(.02)


def test_split_adjusted_signal_series_handles_reverse_split_and_preserves_volume() -> None:
    bars = [bar(date(2021, 7, 30), 10, 800), bar(date(2021, 8, 2), 81, 900)]
    splits = [CorporateAction(date=date(2021, 8, 2), split="1/8")]
    adjusted = split_adjusted_signal_series(bars, splits)
    assert adjusted[0]["close"] == 80
    assert adjusted[0]["volume"] == 800


def test_index_membership_and_tradeability_are_independent_concepts() -> None:
    record = membership(start="2015-01-01", end="2020-01-02")
    prices_continue_until = date(2021, 1, 1)
    assert not record.is_member_on(date(2020, 2, 1), end_date_inclusive=False)
    assert date(2020, 2, 1) <= prices_continue_until


def test_terminal_event_classification_preserves_non_terminal_index_removal() -> None:
    assert classify_terminal_event(acquisition=True) is TerminalEvent.ACQUISITION
    assert classify_terminal_event(bankruptcy=True) is TerminalEvent.BANKRUPTCY
    assert classify_terminal_event(prices_continue=True) is TerminalEvent.INDEX_REMOVAL_STILL_TRADING


def test_missing_price_classification_prioritizes_identity_and_terminal_evidence() -> None:
    assert classify_missing_price(identity_resolved=False, trading_session=True,
                                  terminal_window=False, provider_confirmed_gap=False) is MissingPriceCategory.IDENTITY_FAILURE
    assert classify_missing_price(identity_resolved=True, trading_session=True,
                                  terminal_window=True, provider_confirmed_gap=False) is MissingPriceCategory.TERMINAL_EVENT


def test_post_removal_price_availability_uses_sessions_after_exclusive_end() -> None:
    sessions = [date(2024, 1, day) for day in (2, 3, 4, 5, 8, 9)]
    result = post_removal_availability(sessions, set(sessions[2:]), date(2024, 1, 4), (1, 5))
    assert result == {1: True, 5: None}


def test_lookahead_classification_separates_identity_from_eligibility() -> None:
    assert classify_lookahead_field("membership_effective_date") is LookaheadClass.SAFE_AT_DATE
    assert classify_lookahead_field("future_symbol_change") is LookaheadClass.IDENTITY_ONLY_RETROSPECTIVE
    assert classify_lookahead_field("future_membership") is LookaheadClass.UNSAFE_FOR_ELIGIBILITY
