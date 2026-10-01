from dataclasses import dataclass
from datetime import date
from typing import Any

from app.schemas.market_data import MarketBar


@dataclass(frozen=True)
class AliasInterval:
    security_id: str
    historical_ticker: str
    valid_from: date
    valid_to: date | None
    provider_symbol: str
    provider: str
    identifiers: tuple[tuple[str, str], ...]
    evidence: str
    confidence: str

    def active_on(self, session: date) -> bool:
        return self.valid_from <= session and (self.valid_to is None or session < self.valid_to)


@dataclass(frozen=True)
class LogicalBar:
    security_id: str
    historical_ticker: str
    provider_symbol: str
    provider: str
    bar: MarketBar


def build_linear_alias_chain(
    row: dict[str, Any], *, predecessor_override: str | None = None,
    replacement_identity: dict[str, Any] | None = None,
    symbol_changes_override: list[dict[str, Any]] | None = None,
) -> list[AliasInterval]:
    """Build only documentary linear ticker chains; ambiguous forks fail closed."""
    security_id = str((replacement_identity or {}).get("security_id") or row["security_id"])
    membership = row["membership"]
    start = date.fromisoformat(str(membership.get("start") or membership["first_assertable_membership"]))
    end = date.fromisoformat(str(membership["end"])) if membership.get("end") else None
    identity = row["identity"]
    if replacement_identity:
        identity = {
            "identifiers": replacement_identity["identifiers"],
            "symbol_changes": [],
            "provider_symbol": replacement_identity["provider_symbol"],
            "confidence": replacement_identity["confidence"],
        }
    identifiers = tuple(sorted((str(k), str(v)) for k, v in identity.get("identifiers", {}).items() if v))
    changes = sorted(
        symbol_changes_override
        if symbol_changes_override is not None
        else identity.get("symbol_changes", []),
        key=lambda item: str(item["effective"]),
    )
    # Multiple predecessors entering one ticker are a merger/acquisition fork,
    # not proof that all predecessors share the successor security identity.
    incoming: dict[tuple[str, date], list[str]] = {}
    for item in changes:
        key = (str(item["new_symbol"]), date.fromisoformat(str(item["effective"])))
        incoming.setdefault(key, []).append(str(item["old_symbol"]))
    if predecessor_override:
        changes = [item for item in changes if
                   len(incoming[(str(item["new_symbol"]), date.fromisoformat(str(item["effective"])))]) == 1
                   or str(item["old_symbol"]) == predecessor_override]
        incoming = {}
        for item in changes:
            key = (str(item["new_symbol"]), date.fromisoformat(str(item["effective"])))
            incoming.setdefault(key, []).append(str(item["old_symbol"]))
    if any(len(values) > 1 for values in incoming.values()):
        raise ValueError(f"ambiguous multi-predecessor alias chain for security_id={security_id}")
    current = str((replacement_identity or {}).get("ticker") or membership["ticker"])
    transitions = [(date.fromisoformat(str(item["effective"])), str(item["old_symbol"]),
                    str(item["new_symbol"])) for item in changes]
    # Walk backwards from the membership/current alias, then render forwards.
    selected = []
    cursor = current
    for effective, old, new in sorted(transitions, reverse=True):
        if new == cursor:
            selected.append((effective, old, new))
            cursor = old
    selected.reverse()
    intervals = []
    alias = cursor
    lower = start
    for effective, old, new in selected:
        if effective <= lower:
            alias = new
            continue
        if end is not None and effective >= end:
            continue
        intervals.append(AliasInterval(
            security_id, alias, lower, effective,
            str(identity.get("provider_symbol") or current), "eodhd_adjusted_derived",
            identifiers, f"EODHD symbol-change-history: {old}->{new} effective {effective}",
            str(identity.get("confidence") or "UNRESOLVED"),
        ))
        alias, lower = new, effective
    intervals.append(AliasInterval(
        security_id, alias, lower, end,
        str(identity.get("provider_symbol") or current), "eodhd_adjusted_derived",
        identifiers, "validated POC3 identity and dated symbol-change evidence",
        str(identity.get("confidence") or "UNRESOLVED"),
    ))
    return intervals


def logical_security_history(
    intervals: list[AliasInterval], bars_by_provider_symbol: dict[str, list[MarketBar]],
) -> list[LogicalBar]:
    if not intervals:
        return []
    output: dict[date, LogicalBar] = {}
    for interval in intervals:
        for bar in bars_by_provider_symbol.get(interval.provider_symbol, []):
            session = bar.timestamp.date()
            if not interval.active_on(session):
                continue
            if session in output:
                raise ValueError(f"duplicate logical bar for security_id={interval.security_id} date={session}")
            output[session] = LogicalBar(
                interval.security_id, interval.historical_ticker,
                interval.provider_symbol, interval.provider, bar,
            )
    return [output[key] for key in sorted(output)]
