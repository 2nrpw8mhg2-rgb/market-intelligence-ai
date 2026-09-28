import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from statistics import median
from typing import Any


@dataclass(frozen=True)
class PITMembership:
    security_id: str
    ticker: str
    name: str
    valid_from: date
    valid_to: date | None
    identifiers: tuple[tuple[str, str], ...]
    identity_confidence: str
    reuse_status: str
    symbol_changes: tuple[tuple[str, str, str], ...]
    provenance: str
    eligibility_status: str = "ELIGIBLE"
    exclusion_evidence: str | None = None

    @classmethod
    def from_security_master(
        cls, row: dict[str, Any], exception: dict[str, Any] | None = None
    ) -> "PITMembership":
        membership = row["membership"]
        start = membership.get("start") or membership.get("first_assertable_membership")
        if not start:
            raise ValueError(f"membership has no assertable start (ticker={membership.get('ticker')})")
        identity = row["identity"]
        changes = tuple(sorted(
            (str(item.get("effective")), str(item.get("old_symbol")), str(item.get("new_symbol")))
            for item in identity.get("symbol_changes", [])
        ))
        return cls(
            security_id=str(row.get("security_id") or ""),
            ticker=str(membership["ticker"]),
            name=str(row.get("canonical_name") or ""),
            valid_from=date.fromisoformat(str(start)),
            valid_to=(date.fromisoformat(str(membership["end"])) if membership.get("end") else None),
            identifiers=tuple(sorted((str(key), str(value)) for key, value in
                                     identity.get("identifiers", {}).items() if value)),
            identity_confidence=str(identity.get("confidence") or "UNRESOLVED"),
            reuse_status=str(identity.get("reuse_status") or "UNRESOLVED"),
            symbol_changes=changes,
            provenance="EODHD HistoricalTickerComponents via POC3 security master",
            eligibility_status=(exception or {}).get("classification", "ELIGIBLE"),
            exclusion_evidence=(exception or {}).get("evidence"),
        )

    def eligible_on(self, session: date) -> bool:
        return (self.eligibility_status == "ELIGIBLE"
                and self.valid_from <= session and (self.valid_to is None or session < self.valid_to))


@dataclass(frozen=True)
class SessionSnapshot:
    session: date
    members: tuple[PITMembership, ...]
    additions: tuple[str, ...]
    removals: tuple[str, ...]


@dataclass(frozen=True)
class UniverseValidation:
    snapshots: tuple[SessionSnapshot, ...]
    anomalies: tuple[dict[str, Any], ...]
    deterministic_hash: str
    min_count: int
    max_count: int
    median_count: float

    @property
    def anomaly_counts(self) -> dict[str, int]:
        return dict(sorted(Counter(item["category"] for item in self.anomalies).items()))


def reconstruct_snapshots(records: list[PITMembership], sessions: list[date]) -> tuple[SessionSnapshot, ...]:
    snapshots = []
    previous_ids: set[str] = set()
    previous_by_id: dict[str, PITMembership] = {}
    for session in sessions:
        members = tuple(sorted((record for record in records if record.eligible_on(session)),
                               key=lambda item: (item.security_id, item.ticker)))
        current_by_id = {record.security_id: record for record in members}
        current_ids = set(current_by_id)
        additions = (tuple(sorted(current_by_id[item].ticker for item in current_ids - previous_ids))
                     if snapshots else ())
        removals = (tuple(sorted(previous_by_id[item].ticker for item in previous_ids - current_ids))
                    if snapshots else ())
        snapshots.append(SessionSnapshot(session, members, additions, removals))
        previous_ids, previous_by_id = current_ids, current_by_id
    return tuple(snapshots)


def _intervals_overlap(left: PITMembership, right: PITMembership) -> bool:
    left_end = left.valid_to or date.max
    right_end = right.valid_to or date.max
    return left.valid_from < right_end and right.valid_from < left_end


def _snapshot_hash(snapshots: tuple[SessionSnapshot, ...]) -> str:
    payload = [[item.session.isoformat(), [record.security_id for record in item.members]]
               for item in snapshots]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


def validate_universe(records: list[PITMembership], sessions: list[date]) -> UniverseValidation:
    if not sessions:
        raise ValueError("sessions cannot be empty")
    if sessions != sorted(set(sessions)):
        raise ValueError("sessions must be sorted and unique")
    anomalies: list[dict[str, Any]] = []
    research_start, research_end = sessions[0], sessions[-1]
    relevant = [record for record in records
                if record.valid_from <= research_end
                and (record.valid_to is None or record.valid_to > research_start)]

    for record in relevant:
        interval_sessions = [session for session in sessions
                             if record.valid_from <= session and
                             (record.valid_to is None or session < record.valid_to)]
        if record.eligibility_status == "EXPLICITLY_NON_TRADABLE_OR_INVALID":
            anomalies.append({
                "category": "EXPLICIT_NON_TRADABLE_RECORD", "security_id": record.security_id,
                "ticker": record.ticker, "affected_sessions": len(interval_sessions),
                "first_session": interval_sessions[0] if interval_sessions else None,
                "last_session": interval_sessions[-1] if interval_sessions else None,
                "blocking": False, "evidence": record.exclusion_evidence,
            })
            continue
        affected = interval_sessions
        context = {
            "security_id": record.security_id, "ticker": record.ticker,
            "affected_sessions": len(affected),
            "first_session": affected[0] if affected else None,
            "last_session": affected[-1] if affected else None,
        }
        if record.valid_to is not None and record.valid_from >= record.valid_to:
            anomalies.append({"category": "IMPOSSIBLE_MEMBERSHIP_INTERVAL", **context})
        if not record.security_id:
            anomalies.append({"category": "MISSING_SECURITY_ID", **context})
        if not record.identifiers:
            anomalies.append({"category": "MISSING_STABLE_IDENTIFIER", **context})
        if record.identity_confidence not in {"HIGH", "MEDIUM"}:
            anomalies.append({"category": "UNRESOLVED_ELIGIBLE_IDENTITY", **context})
        if record.reuse_status == "TICKER_REUSE_CONFIRMED":
            anomalies.append({"category": "TICKER_REUSE_ELIGIBLE", **context})

    by_identity: dict[str, list[PITMembership]] = defaultdict(list)
    for record in relevant:
        if record.security_id:
            by_identity[record.security_id].append(record)
    for security_id, identity_records in by_identity.items():
        ordered = sorted(identity_records, key=lambda item: (item.valid_from, item.ticker))
        for left_position, left in enumerate(ordered):
            for right in ordered[left_position + 1:]:
                if _intervals_overlap(left, right):
                    anomalies.append({
                        "category": "OVERLAPPING_IDENTITY_INTERVALS", "security_id": security_id,
                        "ticker": f"{left.ticker}/{right.ticker}",
                    })

    snapshots = reconstruct_snapshots(records, sessions)
    for snapshot in snapshots:
        ids = [record.security_id for record in snapshot.members]
        tickers = [record.ticker for record in snapshot.members]
        for security_id, count in Counter(ids).items():
            if count > 1:
                anomalies.append({"category": "DUPLICATE_ELIGIBLE_SECURITY", "session": snapshot.session,
                                  "security_id": security_id})
        for ticker, count in Counter(tickers).items():
            if count > 1:
                anomalies.append({"category": "DUPLICATE_ELIGIBLE_TICKER", "session": snapshot.session,
                                  "ticker": ticker})
        for record in snapshot.members:
            if snapshot.session < record.valid_from:
                anomalies.append({"category": "ENTRY_BOUNDARY_VIOLATION", "session": snapshot.session,
                                  "security_id": record.security_id, "ticker": record.ticker})
            if record.valid_to is not None and snapshot.session >= record.valid_to:
                anomalies.append({"category": "EXIT_BOUNDARY_VIOLATION", "session": snapshot.session,
                                  "security_id": record.security_id, "ticker": record.ticker})

    counts = [len(snapshot.members) for snapshot in snapshots]
    return UniverseValidation(
        snapshots=snapshots,
        anomalies=tuple(anomalies),
        deterministic_hash=_snapshot_hash(snapshots),
        min_count=min(counts),
        max_count=max(counts),
        median_count=float(median(counts)),
    )
