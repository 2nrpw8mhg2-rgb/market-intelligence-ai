from datetime import UTC, date, datetime, time
from typing import Protocol

from sqlalchemy import Select, and_, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MarketBarRecord, Symbol, Universe, UniverseMembership
from app.schemas.market_data import MarketBar
from app.schemas.universe import MembershipImportRecord


class MarketBarStore(Protocol):
    async def list_daily_bars(
        self,
        ticker: str,
        start_date: date | None = None,
        end_date: date | None = None,
        provider: str | None = None,
    ) -> list[MarketBar]: ...

    async def upsert_daily_bars(
        self, bars: list[MarketBar], *, provider: str
    ) -> int: ...


class MarketBarRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_daily_bars(
        self,
        ticker: str,
        start_date: date | None = None,
        end_date: date | None = None,
        provider: str | None = None,
    ) -> list[MarketBar]:
        statement = (
            select(MarketBarRecord, Symbol.ticker)
            .join(Symbol, Symbol.id == MarketBarRecord.symbol_id)
            .where(Symbol.ticker == ticker.strip().upper())
            .where(MarketBarRecord.timeframe == "1d")
            .order_by(MarketBarRecord.timestamp.asc())
        )
        statement = self._with_date_filters(statement, start_date, end_date)
        if provider:
            statement = statement.where(MarketBarRecord.provider == provider)
        rows = (await self._session.execute(statement)).all()
        return [
            MarketBar(
                ticker=row.ticker,
                timestamp=row.MarketBarRecord.timestamp,
                open=float(row.MarketBarRecord.open),
                high=float(row.MarketBarRecord.high),
                low=float(row.MarketBarRecord.low),
                close=float(row.MarketBarRecord.close),
                volume=row.MarketBarRecord.volume,
            )
            for row in rows
        ]

    async def upsert_daily_bars(
        self, bars: list[MarketBar], *, provider: str
    ) -> int:
        if not bars:
            return 0
        tickers = {bar.ticker for bar in bars}
        if len(tickers) != 1:
            raise ValueError("a bar batch must contain exactly one ticker")
        ticker = next(iter(tickers))
        await self._session.execute(
            insert(Symbol)
            .values(ticker=ticker, asset_type="stock", metadata_json={})
            .on_conflict_do_nothing(index_elements=[Symbol.ticker])
        )
        symbol_id = await self._session.scalar(select(Symbol.id).where(Symbol.ticker == ticker))
        if symbol_id is None:
            raise RuntimeError(f"could not resolve symbol {ticker}")

        values = [
            {
                "symbol_id": symbol_id,
                "timestamp": bar.timestamp.astimezone(UTC),
                "timeframe": "1d",
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "provider": provider,
            }
            for bar in bars
        ]
        statement = insert(MarketBarRecord).values(values)
        statement = statement.on_conflict_do_update(
            constraint="uq_market_bars_identity",
            set_={
                "open": statement.excluded.open,
                "high": statement.excluded.high,
                "low": statement.excluded.low,
                "close": statement.excluded.close,
                "volume": statement.excluded.volume,
                "updated_at": func.now(),
            },
        )
        result = await self._session.execute(statement)
        await self._session.commit()
        return result.rowcount or 0

    @staticmethod
    def _with_date_filters(
        statement: Select,
        start_date: date | None,
        end_date: date | None,
    ) -> Select:
        if start_date:
            statement = statement.where(
                MarketBarRecord.timestamp >= datetime.combine(start_date, time.min, tzinfo=UTC)
            )
        if end_date:
            statement = statement.where(
                MarketBarRecord.timestamp <= datetime.combine(end_date, time.max, tzinfo=UTC)
            )
        return statement


class UniverseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_members(self, universe_name: str, as_of: date) -> list[str]:
        statement = (
            select(Symbol.ticker)
            .join(UniverseMembership, UniverseMembership.symbol_id == Symbol.id)
            .join(Universe, Universe.id == UniverseMembership.universe_id)
            .where(Universe.name == universe_name)
            .where(UniverseMembership.valid_from <= as_of)
            .where(
                and_(
                    (UniverseMembership.valid_to.is_(None))
                    | (UniverseMembership.valid_to >= as_of)
                )
            )
            .order_by(Symbol.ticker)
        )
        return list((await self._session.scalars(statement)).all())

    async def list_membership_records(
        self, universe_name: str, tickers: set[str]
    ) -> list[MembershipImportRecord]:
        if not tickers:
            return []
        statement = (
            select(
                Symbol.ticker,
                UniverseMembership.valid_from,
                UniverseMembership.valid_to,
                UniverseMembership.source,
            )
            .join(UniverseMembership, UniverseMembership.symbol_id == Symbol.id)
            .join(Universe, Universe.id == UniverseMembership.universe_id)
            .where(Universe.name == universe_name)
            .where(Symbol.ticker.in_(tickers))
        )
        return [
            MembershipImportRecord(
                ticker=row.ticker,
                valid_from=row.valid_from,
                valid_to=row.valid_to,
                source=row.source,
            )
            for row in (await self._session.execute(statement)).all()
        ]

    async def upsert_memberships(
        self, universe_name: str, records: list[MembershipImportRecord]
    ) -> int:
        if not records:
            return 0
        await self._session.execute(
            insert(Universe)
            .values(name=universe_name, description=f"{universe_name} point-in-time membership")
            .on_conflict_do_nothing(index_elements=[Universe.name])
        )
        universe_id = await self._session.scalar(
            select(Universe.id).where(Universe.name == universe_name)
        )
        if universe_id is None:
            raise RuntimeError(f"could not resolve universe {universe_name}")
        tickers = sorted({record.ticker for record in records})
        await self._session.execute(
            insert(Symbol)
            .values(
                [
                    {"ticker": ticker, "asset_type": "stock", "metadata_json": {}}
                    for ticker in tickers
                ]
            )
            .on_conflict_do_nothing(index_elements=[Symbol.ticker])
        )
        symbol_rows = (
            await self._session.execute(
                select(Symbol.ticker, Symbol.id).where(Symbol.ticker.in_(tickers))
            )
        ).all()
        symbol_ids = {row.ticker: row.id for row in symbol_rows}
        values = [
            {
                "universe_id": universe_id,
                "symbol_id": symbol_ids[record.ticker],
                "valid_from": record.valid_from,
                "valid_to": record.valid_to,
                "source": record.source,
            }
            for record in records
        ]
        statement = insert(UniverseMembership).values(values)
        statement = statement.on_conflict_do_update(
            constraint="uq_universe_membership_identity",
            set_={"valid_to": statement.excluded.valid_to, "loaded_at": func.now()},
        )
        result = await self._session.execute(statement)
        await self._session.commit()
        return result.rowcount or 0
