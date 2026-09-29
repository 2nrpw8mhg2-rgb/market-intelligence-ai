from datetime import date

from app.research.fixed_rebuilt import (
    TemporalAlias, TemporalAliasResolver, classify_incomplete_horizon,
    compare_matched_events, deterministic_event_digest, event_identity_map,
    event_metrics, horizon_completeness, map_fixed_universe_events, map_original_events,
    paired_event_metrics, score_bucket,
)


def alias(security_id: str, ticker: str, start: str, end: str | None = None,
          provider_symbol: str | None = None) -> TemporalAlias:
    return TemporalAlias(
        security_id=security_id, historical_ticker=ticker,
        valid_from=date.fromisoformat(start), valid_to=date.fromisoformat(end) if end else None,
        provider_symbol=provider_symbol or ticker, provider="validated",
    )


def event(ticker="OLD", when="2024-01-02", score=40.0, result20=0.1, result60=0.2):
    return {
        "ticker": ticker, "signal_date": when, "entry_price": 10.0,
        "relative_volume": 2.0, "score": score,
        "outcomes": [
            {"horizon": h, "stock_return": (result20 if h == 20 else result60 if h == 60 else 0.01),
             "excess_return": 0.0, "forward_data_complete": True}
            for h in (1, 5, 10, 20, 60)
        ],
    }


def test_date_aware_alias_mapping_preserves_security_through_ticker_change() -> None:
    resolver = TemporalAliasResolver([
        alias("issuer", "OLD", "2020-01-01", "2024-01-03", "NEW"),
        alias("issuer", "NEW", "2024-01-03", provider_symbol="NEW"),
    ])
    assert resolver.resolve("OLD", date(2024, 1, 2)).security_id == "issuer"
    assert resolver.resolve("NEW", date(2024, 1, 2)).historical_alias == "OLD"
    assert resolver.resolve("NEW", date(2024, 1, 3)).historical_alias == "NEW"


def test_ticker_reuse_isolated_by_date_and_overlap_fails_closed() -> None:
    resolver = TemporalAliasResolver([
        alias("old-security", "ABC", "2010-01-01", "2015-01-01"),
        alias("new-security", "ABC", "2020-01-01"),
    ])
    assert resolver.resolve("ABC", date(2014, 1, 2)).security_id == "old-security"
    assert resolver.resolve("ABC", date(2024, 1, 2)).security_id == "new-security"
    ambiguous = TemporalAliasResolver([
        alias("one", "ABC", "2020-01-01"), alias("two", "ABC", "2021-01-01")
    ])
    assert ambiguous.resolve("ABC", date(2024, 1, 2)) is None


def test_unmapped_events_are_retained_for_audit() -> None:
    mapped, unmapped = map_original_events([event(ticker="MISSING")], TemporalAliasResolver([]))
    assert mapped == []
    assert unmapped[0]["ticker"] == "MISSING"
    assert "unique dated alias" in unmapped[0]["reason"]


def test_event_matching_uses_security_id_and_signal_date_not_ticker() -> None:
    resolver = TemporalAliasResolver([
        alias("issuer", "OLD", "2020-01-01", "2024-01-03", "NEW"),
        alias("issuer", "NEW", "2024-01-03", provider_symbol="NEW"),
    ])
    left = event_identity_map(map_original_events([event("OLD", "2024-01-02")], resolver)[0])
    right = event_identity_map(map_original_events([event("NEW", "2024-01-02")], resolver)[0])
    summary, _ = compare_matched_events(left, right)
    assert summary["entry_price"]["comparable"] == 1
    assert left.keys() == right.keys()


def test_fixed_universe_current_ticker_resolves_to_dated_alias_via_security_id() -> None:
    resolver = TemporalAliasResolver([
        alias("issuer", "OLD", "2020-01-01", "2024-01-03", "NEW"),
        alias("issuer", "NEW", "2024-01-03", provider_symbol="NEW"),
    ])
    mapped, unmapped = map_fixed_universe_events(
        [event("NEW", "2024-01-02")], {"NEW": "issuer"}, resolver
    )
    assert not unmapped
    assert mapped[0][0].security_id == "issuer"
    assert mapped[0][0].historical_alias == "OLD"


def test_fixed_universe_extends_identity_before_index_membership_without_ticker_fallback() -> None:
    resolver = TemporalAliasResolver([
        alias("issuer", "CURRENT", "2024-01-03", provider_symbol="CURRENT")
    ])
    mapped, unmapped = map_fixed_universe_events(
        [event("CURRENT", "2024-01-02")], {"CURRENT": "issuer"}, resolver
    )
    assert not unmapped
    assert mapped[0][0].security_id == "issuer"


def test_consistency_diagnostics_quantify_one_basis_point_threshold() -> None:
    resolver = TemporalAliasResolver([alias("issuer", "OLD", "2020-01-01")])
    left = event_identity_map(map_original_events([event(result20=0.1)], resolver)[0])
    right = event_identity_map(map_original_events([event(result20=0.1002)], resolver)[0])
    summary, rows = compare_matched_events(left, right)
    assert summary["20_session_return"]["over_1bp"] == 1
    assert rows[0]["difference_bp"] >= 2 - 1e-9


def test_horizon_completeness_keeps_each_horizon_separate() -> None:
    item = event()
    item["outcomes"][-1]["forward_data_complete"] = False
    result = horizon_completeness([item])
    assert result["20"] == {"signals": 1, "completed": 1, "incomplete": 0, "metric_n": 1}
    assert result["60"] == {"signals": 1, "completed": 0, "incomplete": 1, "metric_n": 0}
    assert event_metrics([item], 60)["n"] == 0


def test_incomplete_horizon_distinguishes_window_truncation_and_temporary_halt() -> None:
    sessions = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)]
    assert classify_incomplete_horizon(
        target=date(2024, 2, 1), research_end=date(2024, 1, 31),
        expected_sessions=sessions, available_sessions=set(sessions),
    ) == "RESEARCH_WINDOW_TRUNCATION"
    assert classify_incomplete_horizon(
        target=date(2024, 1, 4), research_end=date(2024, 1, 31),
        expected_sessions=sessions, available_sessions={sessions[0], sessions[2]},
    ) == "TEMPORARY_TRADING_HALT"


def test_score_bucket_exact_boundaries_and_deterministic_digest() -> None:
    assert [score_bucket(value) for value in (20, 40, 60, 80)] == [
        "20-40", "40-60", "60-80", "80-100"
    ]
    events = [event("B", "2024-01-03"), event("A", "2024-01-02")]
    assert deterministic_event_digest(events) == deterministic_event_digest(reversed(events))
