import re
import uuid
from collections import defaultdict
from datetime import date
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.eodhd.models import CorporateAction, EODBar, HistoricalConstituent, parse_split_factor


class Confidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNRESOLVED = "UNRESOLVED"


class StartDateStatus(StrEnum):
    RESOLVED_EXACT = "RESOLVED_EXACT"
    RESOLVED_BOUNDED = "RESOLVED_BOUNDED"
    PRE_HISTORY_MEMBER = "PRE_HISTORY_MEMBER"
    UNRESOLVED = "UNRESOLVED"


class ReuseStatus(StrEnum):
    TICKER_REUSE_CONFIRMED = "TICKER_REUSE_CONFIRMED"
    TICKER_REUSE_SUSPECTED = "TICKER_REUSE_SUSPECTED"
    NO_REUSE_EVIDENCE = "NO_REUSE_EVIDENCE"
    UNRESOLVED = "UNRESOLVED"


class TerminalEvent(StrEnum):
    ACQUISITION = "ACQUISITION"
    MERGER = "MERGER"
    BANKRUPTCY = "BANKRUPTCY"
    DELISTING = "DELISTING"
    TICKER_CHANGE = "TICKER_CHANGE"
    INDEX_REMOVAL_STILL_TRADING = "INDEX_REMOVAL_STILL_TRADING"
    DATA_GAP = "DATA_GAP"
    UNKNOWN = "UNKNOWN"


class MissingPriceCategory(StrEnum):
    IDENTITY_FAILURE = "IDENTITY_FAILURE"
    NON_TRADING_DAY = "NON_TRADING_DAY"
    TERMINAL_EVENT = "TERMINAL_EVENT"
    PROVIDER_DATA_GAP = "PROVIDER_DATA_GAP"
    UNRESOLVED = "UNRESOLVED"


class LookaheadClass(StrEnum):
    SAFE_AT_DATE = "SAFE_AT_DATE"
    IDENTITY_ONLY_RETROSPECTIVE = "IDENTITY_ONLY_RETROSPECTIVE"
    UNSAFE_FOR_ELIGIBILITY = "UNSAFE_FOR_ELIGIBILITY"
    UNKNOWN = "UNKNOWN"


class SecurityAlias(BaseModel):
    ticker: str
    exchange: str | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    source: str
    confidence: Confidence
    evidence: list[str] = Field(default_factory=list)

    def valid_on(self, session: date) -> bool:
        return ((self.valid_from is None or self.valid_from <= session)
                and (self.valid_to is None or session <= self.valid_to))


class ExperimentalSecurity(BaseModel):
    security_id: uuid.UUID
    canonical_name: str
    identifiers: dict[str, str] = Field(default_factory=dict)
    aliases: list[SecurityAlias]
    confidence: Confidence
    evidence: list[str] = Field(default_factory=list)


STOP_WORDS = {
    "inc", "incorporated", "corp", "corporation", "company", "co", "ltd", "limited",
    "plc", "class", "common", "stock", "holdings", "holding", "group", "the",
}


def name_tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", value.lower()) if token not in STOP_WORDS and len(token) > 1}


def name_similarity(left: str, right: str) -> float:
    a, b = name_tokens(left), name_tokens(right)
    return len(a & b) / len(a | b) if a | b else 0.0


def reuse_status(membership_name: str, reference_name: str | None) -> ReuseStatus:
    if not reference_name:
        return ReuseStatus.UNRESOLVED
    score = name_similarity(membership_name, reference_name)
    if score == 0:
        return ReuseStatus.TICKER_REUSE_CONFIRMED
    if score < .5:
        return ReuseStatus.TICKER_REUSE_SUSPECTED
    return ReuseStatus.NO_REUSE_EVIDENCE


def stable_security_id(record: HistoricalConstituent, identifiers: dict[str, Any]) -> uuid.UUID:
    for key in ("OpenFigi", "ISIN", "CUSIP", "CIK", "LEI"):
        if identifiers.get(key):
            return uuid.uuid5(uuid.NAMESPACE_URL, f"eodhd:{key}:{identifiers[key]}")
    return uuid.uuid5(uuid.NAMESPACE_URL, f"eodhd:unresolved:{record.code}:{record.name}:{record.end_date}")


def classify_null_start(record: HistoricalConstituent, coverage_start: date) -> StartDateStatus:
    if record.start_date is not None:
        return StartDateStatus.RESOLVED_EXACT
    # EODHD's flat S&P log begins at a provider coverage boundary. NULL is not
    # converted into a fabricated date; it records that the exact entry predates
    # the observable interval (including legacy rows that ended before it).
    return StartDateStatus.PRE_HISTORY_MEMBER


def classify_terminal_event(*, acquisition: bool = False, bankruptcy: bool = False,
                            ticker_change: bool = False, prices_continue: bool = False) -> TerminalEvent:
    if acquisition:
        return TerminalEvent.ACQUISITION
    if bankruptcy:
        return TerminalEvent.BANKRUPTCY
    if ticker_change:
        return TerminalEvent.TICKER_CHANGE
    if prices_continue:
        return TerminalEvent.INDEX_REMOVAL_STILL_TRADING
    return TerminalEvent.UNKNOWN


def classify_missing_price(*, identity_resolved: bool, trading_session: bool,
                           terminal_window: bool, provider_confirmed_gap: bool) -> MissingPriceCategory:
    if not identity_resolved:
        return MissingPriceCategory.IDENTITY_FAILURE
    if not trading_session:
        return MissingPriceCategory.NON_TRADING_DAY
    if terminal_window:
        return MissingPriceCategory.TERMINAL_EVENT
    if provider_confirmed_gap:
        return MissingPriceCategory.PROVIDER_DATA_GAP
    return MissingPriceCategory.UNRESOLVED


def classify_lookahead_field(field: str) -> LookaheadClass:
    if field in {"membership_effective_date", "price", "split_effective_date"}:
        return LookaheadClass.SAFE_AT_DATE
    if field in {"current_identifiers", "future_symbol_change", "delisted_directory"}:
        return LookaheadClass.IDENTITY_ONLY_RETROSPECTIVE
    if field in {"future_membership", "future_acquisition", "future_terminal_value"}:
        return LookaheadClass.UNSAFE_FOR_ELIGIBILITY
    return LookaheadClass.UNKNOWN


def post_removal_availability(
    sessions: list[date], available_dates: set[date], end_date: date | None,
    horizons: tuple[int, ...] = (1, 5, 10, 20, 60),
) -> dict[int, bool | None]:
    if end_date is None:
        return {horizon: None for horizon in horizons}
    after = [session for session in sessions if session >= end_date]
    return {
        horizon: (None if len(after) < horizon else all(day in available_dates for day in after[:horizon]))
        for horizon in horizons
    }


def build_symbol_change_graph(changes: list[dict[str, Any]]) -> dict[str, Any]:
    edges: dict[str, set[str]] = defaultdict(set)
    for item in changes:
        edges[str(item["old_symbol"]).upper()].add(str(item["new_symbol"]).upper())
    chains = []
    cycles = []
    for origin in sorted(edges):
        paths = [(origin, [origin])]
        while paths:
            node, path = paths.pop()
            next_nodes = edges.get(node, set())
            if not next_nodes:
                if len(path) > 1:
                    chains.append(path)
                continue
            for target in sorted(next_nodes):
                if target in path:
                    cycles.append(path + [target])
                else:
                    paths.append((target, path + [target]))
    unique_chains = sorted({tuple(chain) for chain in chains}, key=lambda item: (len(item), item))
    return {
        "edges": sum(len(values) for values in edges.values()),
        "chains": [list(item) for item in unique_chains],
        "multi_hop_chains": [list(item) for item in unique_chains if len(item) > 2],
        "cycles": cycles,
    }


def split_adjusted_signal_series(bars: list[EODBar], splits: list[CorporateAction]) -> list[dict[str, Any]]:
    events = sorted((item.date, parse_split_factor(item.split)) for item in splits if item.split)
    result = []
    for bar in sorted(bars, key=lambda item: item.date):
        future_factor = 1.0
        for event_date, factor in events:
            if event_date > bar.date:
                future_factor *= factor
        result.append({
            "date": bar.date, "open": bar.open / future_factor, "high": bar.high / future_factor,
            "low": bar.low / future_factor, "close": bar.close / future_factor,
            # EODHD documents base EOD volume as already split-adjusted.
            "volume": bar.volume, "cumulative_future_split_factor": future_factor,
        })
    return result
