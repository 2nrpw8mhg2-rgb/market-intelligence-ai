from datetime import date

from app.pit.universe_validation import PITMembership, reconstruct_snapshots, validate_universe


def member(security_id: str, ticker: str, start: str, end: str | None = None,
           *, changes=(), reuse="NO_REUSE_EVIDENCE") -> PITMembership:
    return PITMembership(
        security_id=security_id, ticker=ticker, name=ticker,
        valid_from=date.fromisoformat(start), valid_to=date.fromisoformat(end) if end else None,
        identifiers=(("CIK", security_id),), identity_confidence="HIGH", reuse_status=reuse,
        symbol_changes=tuple(changes), provenance="test",
    )


def test_entry_boundary_is_inclusive_and_no_signal_is_possible_before_entry() -> None:
    record = member("1", "NEW", "2024-01-03")
    assert not record.eligible_on(date(2024, 1, 2))
    assert record.eligible_on(date(2024, 1, 3))


def test_exit_boundary_is_exclusive_and_no_signal_is_possible_on_or_after_exit() -> None:
    record = member("1", "OLD", "2020-01-01", "2024-01-03")
    assert record.eligible_on(date(2024, 1, 2))
    assert not record.eligible_on(date(2024, 1, 3))


def test_ticker_change_preserves_security_identity_without_overlap() -> None:
    records = [
        member("issuer-1", "FB", "2020-01-01", "2022-06-09",
               changes=(("2022-06-09", "FB", "META"),)),
        member("issuer-1", "META", "2022-06-09"),
    ]
    sessions = [date(2022, 6, 8), date(2022, 6, 9)]
    snapshots = reconstruct_snapshots(records, sessions)
    assert [item.ticker for item in snapshots[0].members] == ["FB"]
    assert [item.ticker for item in snapshots[1].members] == ["META"]
    assert not validate_universe(records, sessions).anomalies


def test_ticker_reuse_does_not_inherit_old_security_membership() -> None:
    old = member("old-security", "ABC", "2010-01-01", "2015-01-01")
    modern = member("modern-security", "ABC", "2020-01-01")
    assert not old.eligible_on(date(2024, 1, 2))
    assert modern.eligible_on(date(2024, 1, 2))
    snapshot = reconstruct_snapshots([old, modern], [date(2024, 1, 2)])[0]
    assert [item.security_id for item in snapshot.members] == ["modern-security"]


def test_duplicate_eligible_security_is_reported_not_silently_deduplicated() -> None:
    records = [member("same", "A", "2020-01-01"), member("same", "B", "2020-01-01")]
    result = validate_universe(records, [date(2024, 1, 2)])
    categories = [item["category"] for item in result.anomalies]
    assert "OVERLAPPING_IDENTITY_INTERVALS" in categories
    assert "DUPLICATE_ELIGIBLE_SECURITY" in categories


def test_reconstruction_has_no_duplicate_members_and_is_deterministic() -> None:
    records = [member("2", "B", "2020-01-01"), member("1", "A", "2020-01-01")]
    sessions = [date(2024, 1, 2), date(2024, 1, 3)]
    first = validate_universe(records, sessions)
    second = validate_universe(list(reversed(records)), sessions)
    assert not first.anomalies
    assert first.deterministic_hash == second.deterministic_hash
    assert all(len({item.security_id for item in snapshot.members}) == len(snapshot.members)
               for snapshot in first.snapshots)


def test_explicit_non_tradable_record_is_retained_but_never_eligible() -> None:
    record = member("spin-record", "MRP_OLD", "2025-01-21", "2025-02-10")
    record = PITMembership(**{
        **record.__dict__,
        "eligibility_status": "EXPLICITLY_NON_TRADABLE_OR_INVALID",
        "exclusion_evidence": "official index and issuer evidence",
    })
    sessions = [date(2025, 2, 7)]
    result = validate_universe([record], sessions)
    assert result.snapshots[0].members == ()
    assert result.anomalies == ({
        "category": "EXPLICIT_NON_TRADABLE_RECORD", "security_id": "spin-record",
        "ticker": "MRP_OLD", "affected_sessions": 1,
        "first_session": date(2025, 2, 7), "last_session": date(2025, 2, 7),
        "blocking": False, "evidence": "official index and issuer evidence",
    },)
