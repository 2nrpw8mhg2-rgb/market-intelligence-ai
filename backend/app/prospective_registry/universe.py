from datetime import UTC, datetime
from typing import Iterable

from app.prospective_registry.canonical import canonical_hash
from app.prospective_registry.models import PendingMembershipChange, UniverseConfirmation


def universe_snapshot_hash(memberships: Iterable[dict]) -> str:
    ordered = sorted(
        memberships,
        key=lambda row: (str(row["security_id"]), str(row["ticker"])),
    )
    return canonical_hash(ordered)


def validate_universe_confirmation(
    confirmation: UniverseConfirmation, *, session_memberships: list[dict],
    now: datetime,
) -> str:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if confirmation.operator_confirmed_at > now.astimezone(UTC):
        raise ValueError("universe confirmation cannot be future-dated")
    actual = universe_snapshot_hash(session_memberships)
    if actual != confirmation.universe_snapshot_hash:
        raise ValueError("confirmed universe hash does not match the session snapshot")
    effective_unapplied = [
        change for change in confirmation.pending_changes
        if change.effective_at <= now.astimezone(UTC)
    ]
    if effective_unapplied:
        raise ValueError("confirmation contains an effective change still marked pending")
    by_security = {
        str(row["security_id"]): str(row["ticker"])
        for row in session_memberships
    }
    for change in confirmation.pending_changes:
        if change.action == "ADD" and change.security_id in by_security:
            raise ValueError("announced ADD was applied before its effective time")
        if change.action == "REMOVE" and change.security_id not in by_security:
            raise ValueError("announced REMOVE was applied before its effective time")
        if change.action == "TICKER_CHANGE":
            current = by_security.get(change.security_id)
            if current != change.old_ticker:
                raise ValueError("announced ticker change was applied before its effective time")
    return actual


def apply_membership_changes(
    members: dict[str, str], changes: Iterable[PendingMembershipChange], *, as_of: datetime,
) -> dict[str, str]:
    """Pure audit helper: announcement alone never changes eligibility."""
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    result = dict(members)
    for change in sorted(changes, key=lambda item: item.effective_at):
        if change.effective_at > as_of.astimezone(UTC):
            continue
        if change.action == "ADD":
            if change.security_id in result:
                raise ValueError("ADD reuses an existing security_id")
            if not change.new_ticker:
                raise ValueError("ADD requires new_ticker")
            result[change.security_id] = change.new_ticker
        elif change.action == "REMOVE":
            if change.security_id not in result:
                raise ValueError("REMOVE references an unknown security_id")
            result.pop(change.security_id)
        else:
            current = result.get(change.security_id)
            if current != change.old_ticker:
                raise ValueError("ticker change does not match the existing identity alias")
            assert change.new_ticker is not None
            result[change.security_id] = change.new_ticker
    return result
