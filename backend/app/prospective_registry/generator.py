from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from app.database.repositories import MarketBarRepository, UniverseRepository
from app.market_data.calendar import NYSETradingCalendar
from app.prospective_registry.canonical import canonical_hash
from app.prospective_registry.models import InputSnapshot, SignalPayload, UniverseConfirmation
from app.prospective_registry.snapshots import ContentAddressedSnapshotStore
from app.prospective_registry.timing import ProspectiveTiming
from app.prospective_registry.universe import validate_universe_confirmation
from app.schemas.market_data import MarketBar
from app.schemas.scanner import ScanMode, ScanRequest
from app.services.scanner import ScannerService


@dataclass(frozen=True)
class PreparedRegistration:
    session_date: date
    signals: tuple[SignalPayload, ...]
    input_snapshot_hash: str
    pit_universe_hash: str
    parameter_hash: str
    scanner_summary: dict[str, Any]


class _SnapshotUniverse:
    def __init__(self, tickers: list[str]) -> None:
        self._tickers = tickers

    async def current_members(self) -> list[str]:
        return list(self._tickers)

    async def members(self, as_of: date) -> list[str]:
        return list(self._tickers)


class _SnapshotBars:
    def __init__(self, values: dict[str, list[MarketBar]]) -> None:
        self._values = values

    async def list_daily_bars(
        self, ticker: str, start_date: date | None = None,
        end_date: date | None = None, provider: str | None = None,
    ) -> list[MarketBar]:
        return [
            bar for bar in self._values.get(ticker, [])
            if (start_date is None or bar.timestamp.date() >= start_date)
            and (end_date is None or bar.timestamp.date() <= end_date)
        ]


class _NoopOpportunityStore:
    async def upsert(self, opportunities, configuration) -> None:
        return None


class _PinnedCalendar:
    def __init__(self, session: date) -> None:
        self._session = session
        self._delegate = NYSETradingCalendar()
        self.name = self._delegate.name

    def latest_complete_session(self, now: datetime, delay_minutes: int = 0) -> date:
        return self._session

    def __getattr__(self, name: str):
        return getattr(self._delegate, name)


class FrozenProspectiveSignalGenerator:
    """Runs the existing scanner against one immutable, identity-mapped snapshot."""

    def __init__(
        self, *, universe_repository: UniverseRepository,
        market_bars: MarketBarRepository, snapshot_store: ContentAddressedSnapshotStore,
        provider: str = "massive",
    ) -> None:
        self._universe_repository = universe_repository
        self._market_bars = market_bars
        self._snapshot_store = snapshot_store
        self._provider = provider

    async def prepare(
        self, *, session_date: date, confirmation: UniverseConfirmation,
        data_ready_at: datetime, data_ready_evidence: str, captured_at: datetime,
    ) -> PreparedRegistration:
        if captured_at.tzinfo is None or data_ready_at.tzinfo is None:
            raise ValueError("snapshot timestamps must be timezone-aware")
        if confirmation.session_date != session_date:
            raise ValueError("universe confirmation is for a different session")
        if confirmation.operator_confirmed_at < ProspectiveTiming().session_close(session_date):
            raise ValueError("universe confirmation predates the session close")
        memberships_models = await self._universe_repository.list_period_memberships(
            "SP500", session_date, session_date,
        )
        memberships = [item.model_dump(mode="json") for item in memberships_models]
        if not memberships:
            raise RuntimeError("PIT universe is unavailable for the requested session")
        ids = [str(item["security_id"]) for item in memberships]
        tickers = [str(item["ticker"]) for item in memberships]
        if len(ids) != len(set(ids)):
            raise RuntimeError("PIT universe contains duplicate security identities")
        if len(tickers) != len(set(tickers)):
            raise RuntimeError("PIT universe contains ambiguous ticker aliases")
        universe_hash = validate_universe_confirmation(
            confirmation, session_memberships=memberships, now=captured_at,
        )

        bars_by_ticker: dict[str, list[MarketBar]] = {}
        bars_by_security: dict[str, tuple[dict[str, Any], ...]] = {}
        security_by_ticker: dict[str, str] = {}
        for membership in sorted(memberships, key=lambda row: (row["security_id"], row["ticker"])):
            ticker = str(membership["ticker"])
            security_id = str(membership["security_id"])
            bars = await self._market_bars.list_daily_bars(
                ticker, end_date=session_date, provider=self._provider,
            )
            bars_by_ticker[ticker] = bars
            bars_by_security[security_id] = tuple(
                bar.model_dump(mode="json") for bar in bars
            )
            security_by_ticker[ticker] = security_id

        snapshot = InputSnapshot(
            session_date=session_date,
            captured_at=captured_at,
            data_ready_at=data_ready_at,
            data_ready_evidence=data_ready_evidence,
            provider=self._provider,
            provider_metadata={
                "timeframe": "1d",
                "price_representation": "unadjusted_ohlcv_as_persisted",
                "availability_timestamp_source": data_ready_evidence,
            },
            universe_confirmation=confirmation,
            memberships=tuple(memberships),
            bars_by_security=bars_by_security,
        )
        snapshot_hash = self._snapshot_store.put(snapshot.model_dump(mode="json"))

        request = ScanRequest(mode=ScanMode.LATEST)
        response = await ScannerService(
            universe=_SnapshotUniverse(sorted(tickers)),
            bars=_SnapshotBars(bars_by_ticker),
            opportunities=_NoopOpportunityStore(),
            calendar=_PinnedCalendar(session_date),
            provider=self._provider,
            now=lambda: captured_at.astimezone(UTC),
            provider_delay_minutes=0,
        ).scan(request)
        unsafe_reasons = {"MISSING_MARKET_DATA", "INVALID_FEATURES", "PROCESSING_ERROR"}
        unsafe = {
            ticker: reason for ticker, reason in response.summary.exclusions.items()
            if reason in unsafe_reasons
        }
        if response.status != "COMPLETED" or response.summary.symbols_failed or unsafe:
            raise RuntimeError(
                "signal inputs failed closed: "
                + ", ".join(f"{ticker}={reason}" for ticker, reason in sorted(unsafe.items()))
            )

        ordered = sorted(
            response.opportunities,
            key=lambda item: (-item.score, security_by_ticker[item.ticker]),
        )
        signals = tuple(
            SignalPayload(
                security_id=security_by_ticker[item.ticker],
                ticker=item.ticker,
                score=item.score,
                rank=rank,
            )
            for rank, item in enumerate(ordered, start=1)
        )
        return PreparedRegistration(
            session_date=session_date,
            signals=signals,
            input_snapshot_hash=snapshot_hash,
            pit_universe_hash=universe_hash,
            parameter_hash=canonical_hash(request.parameters.model_dump(mode="json")),
            scanner_summary=response.summary.model_dump(mode="json"),
        )
