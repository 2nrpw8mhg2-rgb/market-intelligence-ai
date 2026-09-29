import hashlib
import json
import math
import statistics
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable

from app.market_data.calendar import NYSETradingCalendar


def normalize_ticker(value: str) -> str:
    return value.strip().upper().replace(".", "-")


@dataclass(frozen=True)
class TemporalAlias:
    security_id: str
    historical_ticker: str
    valid_from: date
    valid_to: date | None
    provider_symbol: str
    provider: str

    def active_on(self, session: date) -> bool:
        return self.valid_from <= session and (self.valid_to is None or session < self.valid_to)


@dataclass(frozen=True)
class ResolvedEventIdentity:
    security_id: str
    original_ticker: str
    historical_alias: str
    provider_symbol: str
    signal_date: date


class TemporalAliasResolver:
    """Resolve a dated logical security without modern-ticker fallback."""

    def __init__(self, aliases: Iterable[TemporalAlias]) -> None:
        self.aliases = tuple(aliases)
        self._by_label: dict[str, list[TemporalAlias]] = {}
        for item in self.aliases:
            for value in (item.historical_ticker, item.provider_symbol):
                self._by_label.setdefault(normalize_ticker(value), []).append(item)

    @classmethod
    def from_csv_rows(cls, rows: Iterable[dict[str, str]]) -> "TemporalAliasResolver":
        return cls(TemporalAlias(
            security_id=row["security_id"], historical_ticker=row["historical_ticker"],
            valid_from=date.fromisoformat(row["valid_from"]),
            valid_to=date.fromisoformat(row["valid_to"]) if row.get("valid_to") else None,
            provider_symbol=row["provider_symbol"], provider=row["provider"],
        ) for row in rows)

    def resolve(self, ticker: str, session: date) -> ResolvedEventIdentity | None:
        candidates = self._by_label.get(normalize_ticker(ticker), [])
        if not candidates:
            return None
        # Prefer an alias that was itself active on the event date. This permits
        # legitimate ticker reuse to resolve to different securities in disjoint
        # periods without ever using modern ticker equality as identity.
        direct = [item for item in candidates if item.active_on(session)
                  and normalize_ticker(item.historical_ticker) == normalize_ticker(ticker)]
        security_ids = {item.security_id for item in direct}
        if not security_ids:
            # A provider symbol can span a dated ticker change (for example
            # FLT/CPAY). It is usable only when it identifies one logical chain.
            security_ids = {item.security_id for item in candidates
                            if normalize_ticker(item.provider_symbol) == normalize_ticker(ticker)}
        if len(security_ids) != 1:
            return None
        security_id = next(iter(security_ids))
        active = [item for item in self.aliases if item.security_id == security_id
                  and item.active_on(session)]
        if len(active) != 1:
            return None
        item = active[0]
        return ResolvedEventIdentity(
            security_id=security_id, original_ticker=ticker,
            historical_alias=item.historical_ticker,
            provider_symbol=item.provider_symbol, signal_date=session,
        )

    def resolve_security(
        self, security_id: str, original_ticker: str, session: date,
        *, extend_outer_bounds: bool = False,
    ) -> ResolvedEventIdentity | None:
        """Resolve the dated alias after identity was established independently."""
        chain = sorted((item for item in self.aliases if item.security_id == security_id),
                       key=lambda item: item.valid_from)
        active = [item for item in chain if item.active_on(session)]
        # Alias-ledger bounds are index-membership bounds. A fixed/current-
        # universe experiment intentionally evaluates the same proven security
        # before its index entry, so extend only the outer identity segment;
        # never bridge an internal gap or ticker-reuse ambiguity.
        if not active and extend_outer_bounds and chain and session < chain[0].valid_from:
            active = [chain[0]]
        if (not active and extend_outer_bounds and chain and chain[-1].valid_to is not None
                and session >= chain[-1].valid_to):
            active = [chain[-1]]
        if len(active) != 1:
            return None
        item = active[0]
        return ResolvedEventIdentity(
            security_id=security_id, original_ticker=original_ticker,
            historical_alias=item.historical_ticker,
            provider_symbol=item.provider_symbol, signal_date=session,
        )


def map_original_events(
    events: Iterable[dict[str, Any]], resolver: TemporalAliasResolver,
) -> tuple[list[tuple[ResolvedEventIdentity, dict[str, Any]]], list[dict[str, Any]]]:
    mapped = []
    unmapped = []
    for event in events:
        signal_date = date.fromisoformat(str(event["signal_date"]))
        identity = resolver.resolve(str(event["ticker"]), signal_date)
        if identity is None:
            unmapped.append({
                "ticker": event["ticker"], "signal_date": signal_date,
                "reason": "no unique dated alias/security_id mapping",
                "event": event,
            })
        else:
            mapped.append((identity, event))
    return mapped, unmapped


def map_fixed_universe_events(
    events: Iterable[dict[str, Any]], fixed_security_ids: dict[str, str],
    resolver: TemporalAliasResolver,
) -> tuple[list[tuple[ResolvedEventIdentity, dict[str, Any]]], list[dict[str, Any]]]:
    """Map a fixed/current universe through its pre-established security IDs."""
    mapped = []
    unmapped = []
    for event in events:
        ticker = str(event["ticker"])
        signal_date = date.fromisoformat(str(event["signal_date"]))
        security_id = fixed_security_ids.get(ticker)
        identity = (resolver.resolve_security(security_id, ticker, signal_date)
                    if security_id is not None else None)
        if identity is None and security_id is not None:
            identity = resolver.resolve_security(
                security_id, ticker, signal_date, extend_outer_bounds=True
            )
        if identity is None:
            unmapped.append({
                "ticker": ticker, "signal_date": signal_date,
                "reason": "fixed security_id has no unique dated historical alias",
                "event": event,
            })
        else:
            mapped.append((identity, event))
    return mapped, unmapped


def event_identity_map(
    mapped: Iterable[tuple[ResolvedEventIdentity, dict[str, Any]]],
) -> dict[tuple[str, date], tuple[ResolvedEventIdentity, dict[str, Any]]]:
    output = {}
    for identity, event in mapped:
        key = (identity.security_id, identity.signal_date)
        if key in output:
            raise ValueError(f"duplicate event identity: {key}")
        output[key] = (identity, event)
    return output


def outcome(event: dict[str, Any], horizon: int) -> dict[str, Any]:
    return next(item for item in event["outcomes"] if int(item["horizon"]) == horizon)


def basis_point_difference(field: str, original: float, rebuilt: float) -> float:
    if field in {"20_session_return", "60_session_return"}:
        return abs(rebuilt - original) * 10_000
    if field == "score":
        return abs(rebuilt - original) * 100
    if original == 0:
        return math.inf if rebuilt != 0 else 0.0
    return abs(rebuilt / original - 1) * 10_000


def compare_matched_events(
    original: dict[tuple[str, date], tuple[ResolvedEventIdentity, dict[str, Any]]],
    rebuilt: dict[tuple[str, date], tuple[ResolvedEventIdentity, dict[str, Any]]],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    fields = {
        "entry_price": lambda event: event.get("entry_price"),
        "relative_volume": lambda event: event.get("relative_volume"),
        "score": lambda event: event.get("score"),
        "20_session_return": lambda event: outcome(event, 20).get("stock_return"),
        "60_session_return": lambda event: outcome(event, 60).get("stock_return"),
    }
    values: dict[str, list[float]] = {field: [] for field in fields}
    discrepancies = []
    for key in sorted(original.keys() & rebuilt.keys(), key=lambda item: (item[1], item[0])):
        original_identity, original_event = original[key]
        rebuilt_identity, rebuilt_event = rebuilt[key]
        for field, getter in fields.items():
            left, right = getter(original_event), getter(rebuilt_event)
            if left is None or right is None:
                continue
            left, right = float(left), float(right)
            bp = basis_point_difference(field, left, right)
            absolute = abs(right - left)
            values[field].append(absolute)
            discrepancies.append({
                "security_id": key[0], "signal_date": key[1].isoformat(),
                "original_ticker": original_identity.original_ticker,
                "rebuilt_alias": rebuilt_identity.historical_alias,
                "field": field, "original": left, "rebuilt": right,
                "absolute_difference": absolute, "difference_bp": bp,
            })
    summary = {}
    for field, differences in values.items():
        field_rows = [item for item in discrepancies if item["field"] == field]
        over = sum(item["difference_bp"] > 1 for item in field_rows)
        summary[field] = {
            "comparable": len(field_rows), "identical": sum(value <= 1e-12 for value in differences),
            "over_1bp": over, "pct_over_1bp": over / len(field_rows) if field_rows else None,
            "maximum_absolute_difference": max(differences) if differences else None,
            "median_absolute_difference": statistics.median(differences) if differences else None,
        }
    return summary, sorted(discrepancies, key=lambda item: item["difference_bp"], reverse=True)


def horizon_completeness(events: Iterable[dict[str, Any]]) -> dict[str, dict[str, int]]:
    event_list = list(events)
    result = {}
    for horizon in (1, 5, 10, 20, 60):
        completed = sum(bool(outcome(event, horizon)["forward_data_complete"]) for event in event_list)
        result[str(horizon)] = {
            "signals": len(event_list), "completed": completed,
            "incomplete": len(event_list) - completed, "metric_n": completed,
        }
    return result


def event_metrics(events: Iterable[dict[str, Any]], horizon: int) -> dict[str, Any]:
    selected = [item for event in events if (item := outcome(event, horizon))["forward_data_complete"]]
    returns = [float(item["stock_return"]) for item in selected if item.get("stock_return") is not None]
    excess = [float(item["excess_return"]) for item in selected if item.get("excess_return") is not None]
    return {
        "n": len(returns),
        "mean_return": statistics.fmean(returns) if returns else None,
        "median_return": statistics.median(returns) if returns else None,
        "positive_rate": sum(value > 0 for value in returns) / len(returns) if returns else None,
        "mean_excess_return": statistics.fmean(excess) if excess else None,
        "median_excess_return": statistics.median(excess) if excess else None,
    }


def paired_event_metrics(
    original: dict[tuple[str, date], tuple[ResolvedEventIdentity, dict[str, Any]]],
    rebuilt: dict[tuple[str, date], tuple[ResolvedEventIdentity, dict[str, Any]]],
    horizon: int,
) -> dict[str, dict[str, Any]]:
    left = []
    right = []
    for key in original.keys() & rebuilt.keys():
        original_event = original[key][1]
        rebuilt_event = rebuilt[key][1]
        if (outcome(original_event, horizon)["forward_data_complete"]
                and outcome(rebuilt_event, horizon)["forward_data_complete"]):
            left.append(original_event)
            right.append(rebuilt_event)
    original_metrics = event_metrics(left, horizon)
    rebuilt_metrics = event_metrics(right, horizon)
    return {"original_fixed": original_metrics, "fixed_rebuilt": rebuilt_metrics,
            "difference_rebuilt_minus_original": {
                key: rebuilt_metrics[key] - original_metrics[key]
                for key in original_metrics if original_metrics[key] is not None
            }}


def classify_incomplete_horizon(
    *, target: date, research_end: date, expected_sessions: list[date],
    available_sessions: set[date], lifecycle_end: date | None = None,
) -> str:
    if target > research_end:
        return "RESEARCH_WINDOW_TRUNCATION"
    missing = [item for item in expected_sessions if item not in available_sessions]
    if not missing:
        return "COMPLETE"
    if lifecycle_end is not None and min(missing) >= lifecycle_end:
        return "SECURITY_LIFECYCLE_TERMINATION"
    if any(item > max(missing) for item in expected_sessions if item in available_sessions):
        return "TEMPORARY_TRADING_HALT"
    return "GENUINE_MISSING_DATA"


def score_bucket(score: float, boundaries: tuple[float, ...] = (0, 20, 40, 60, 80, 100)) -> str:
    for low, high in zip(boundaries, boundaries[1:]):
        if low <= score < high or (high == boundaries[-1] and score == high):
            return f"{low:g}-{high:g}"
    raise ValueError(f"score outside configured buckets: {score}")


def deterministic_event_digest(events: Iterable[dict[str, Any]]) -> str:
    payload = sorted(({
        "ticker": event["ticker"], "signal_date": str(event["signal_date"]),
        "score": event["score"], "entry_price": event.get("entry_price"),
        "outcomes": event["outcomes"],
    } for event in events), key=lambda item: (item["signal_date"], item["ticker"]))
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def session_count(start: date, end: date) -> int:
    return len(NYSETradingCalendar().trading_days_between(start, end))
