from datetime import UTC, date, datetime, time
import uuid
from typing import Any, Protocol

from sqlalchemy import Select, and_, delete as sa_delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    BacktestEvent, BacktestForwardReturn, BacktestRun, MarketBarRecord,
    MarketRegimeObservation, Opportunity, PortfolioDailyEquity,
    PortfolioSimulationRun, PortfolioSkippedSignal, PortfolioTradeRecord,
    ResearchRun, Security, Strategy, Symbol, Universe, UniverseMembership,
    UniverseSnapshot, UniverseSnapshotMember,
)
from app.schemas.backtesting import BacktestRunResult
from app.schemas.market_data import MarketBar
from app.schemas.research import PortfolioSimulationResult, ResearchResult
from app.schemas.scanner import OpportunityResult
from app.schemas.universe import MembershipImportRecord
from app.schemas.universe import CurrentSnapshotImport


def _chunks(values: list[dict], size: int = 1_000):
    for index in range(0, len(values), size):
        yield values[index:index + size]


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
                volume=float(row.MarketBarRecord.volume),
            )
            for row in rows
        ]

    async def list_security_daily_bars(
        self, security_id: uuid.UUID, ticker: str, start_date: date | None = None,
        end_date: date | None = None, *, providers: tuple[str, ...] = ("massive", "eodhd_adjusted_derived"),
    ) -> tuple[str | None, list[MarketBar]]:
        """Resolve bars through security identity; never fall back to ticker alone."""
        symbol = (await self._session.execute(
            select(Symbol.id, Symbol.security_id)
            .where(Symbol.ticker == ticker.strip().upper())
        )).one_or_none()
        if symbol is None or symbol.security_id != security_id:
            raise PITIdentityResolutionError(
                f"market-data alias is not linked to the requested security_id (ticker={ticker})"
            )
        for provider in providers:
            bars = await self.list_daily_bars(ticker, start_date, end_date, provider)
            if bars:
                return provider, bars
        return None, []

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
        affected = 0
        for chunk in _chunks(values):
            statement = insert(MarketBarRecord).values(chunk)
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
            affected += result.rowcount or 0
        await self._session.commit()
        return affected

    async def daily_bar_diagnostics(
        self, ticker: str, start_date: date, end_date: date, *, provider: str
    ) -> dict:
        statement = (
            select(
                func.count(MarketBarRecord.id).label("bar_count"),
                func.min(MarketBarRecord.timestamp).label("first_timestamp"),
                func.max(MarketBarRecord.timestamp).label("last_timestamp"),
                func.max(MarketBarRecord.updated_at).label("last_updated"),
            )
            .join(Symbol, Symbol.id == MarketBarRecord.symbol_id)
            .where(Symbol.ticker == ticker.strip().upper())
            .where(MarketBarRecord.provider == provider)
            .where(MarketBarRecord.timeframe == "1d")
        )
        statement = self._with_date_filters(statement, start_date, end_date)
        row = (await self._session.execute(statement)).one()
        return {
            "bar_count": row.bar_count,
            "first_session": row.first_timestamp.date() if row.first_timestamp else None,
            "last_session": row.last_timestamp.date() if row.last_timestamp else None,
            "last_updated": row.last_updated,
        }

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
            select(Symbol.ticker, Symbol.security_id.label("symbol_security_id"),
                   UniverseMembership.security_id,
                   UniverseMembership.eligibility_status)
            .join(UniverseMembership, UniverseMembership.symbol_id == Symbol.id)
            .join(Universe, Universe.id == UniverseMembership.universe_id)
            .where(Universe.name == universe_name)
            .where(UniverseMembership.valid_from <= as_of)
            .where(
                and_(
                    (UniverseMembership.valid_to.is_(None))
                    | (UniverseMembership.valid_to > as_of)
                )
            )
            .order_by(Symbol.ticker)
        )
        rows = (await self._session.execute(statement)).all()
        rows = self._validated_membership_rows(rows)
        security_ids = [row.security_id for row in rows]
        if len(security_ids) != len(set(security_ids)):
            raise PITIdentityResolutionError(
                f"duplicate eligible security_id in {universe_name} on {as_of}"
            )
        return [row.ticker for row in rows]

    async def list_current_members(self, universe_name: str) -> list[str]:
        latest_snapshot = (
            select(UniverseSnapshot.id)
            .join(Universe)
            .where(Universe.name == universe_name)
            .order_by(UniverseSnapshot.snapshot_date.desc(), UniverseSnapshot.loaded_at.desc())
            .limit(1)
            .scalar_subquery()
        )
        statement = (
            select(Symbol.ticker)
            .join(UniverseSnapshotMember, UniverseSnapshotMember.symbol_id == Symbol.id)
            .where(UniverseSnapshotMember.snapshot_id == latest_snapshot)
            .order_by(Symbol.ticker)
        )
        return list((await self._session.scalars(statement)).all())

    async def import_current_snapshot(self, universe_name: str, snapshot: CurrentSnapshotImport) -> int:
        await self._session.execute(
            insert(Universe).values(name=universe_name, description="Current constituent snapshots")
            .on_conflict_do_nothing(index_elements=[Universe.name])
        )
        universe_id = await self._session.scalar(select(Universe.id).where(Universe.name == universe_name))
        await self._session.execute(
            insert(Symbol).values([{"ticker": ticker, "asset_type": "stock", "metadata_json": {}} for ticker in snapshot.tickers])
            .on_conflict_do_nothing(index_elements=[Symbol.ticker])
        )
        snapshot_statement = insert(UniverseSnapshot).values(
            universe_id=universe_id, snapshot_date=snapshot.snapshot_date, source=snapshot.source
        ).on_conflict_do_update(
            constraint="uq_universe_snapshot_identity", set_={"loaded_at": func.now()}
        ).returning(UniverseSnapshot.id)
        snapshot_id = (await self._session.execute(snapshot_statement)).scalar_one()
        symbol_rows = (await self._session.execute(select(Symbol.ticker, Symbol.id).where(Symbol.ticker.in_(snapshot.tickers)))).all()
        # A re-import replaces this snapshot's exact membership, not historical records.
        await self._session.execute(sa_delete(UniverseSnapshotMember).where(UniverseSnapshotMember.snapshot_id == snapshot_id))
        await self._session.execute(insert(UniverseSnapshotMember).values([
            {"snapshot_id": snapshot_id, "symbol_id": row.id} for row in symbol_rows
        ]))
        await self._session.commit()
        return len(symbol_rows)

    async def list_membership_records(
        self, universe_name: str, tickers: set[str]
    ) -> list[MembershipImportRecord]:
        if not tickers:
            return []
        statement = (
            select(
                Symbol.ticker,
                Symbol.name.label("security_name"),
                Symbol.security_id.label("symbol_security_id"),
                UniverseMembership.security_id,
                UniverseMembership.valid_from,
                UniverseMembership.valid_to,
                UniverseMembership.source,
                UniverseMembership.source_confidence,
                UniverseMembership.provenance_json,
                UniverseMembership.eligibility_status,
            )
            .join(UniverseMembership, UniverseMembership.symbol_id == Symbol.id)
            .join(Universe, Universe.id == UniverseMembership.universe_id)
            .where(Universe.name == universe_name)
            .where(Symbol.ticker.in_(tickers))
        )
        return [
            MembershipImportRecord(
                security_id=row.security_id,
                ticker=row.ticker,
                security_name=row.security_name,
                valid_from=row.valid_from,
                valid_to=row.valid_to,
                source=row.source,
                source_confidence=row.source_confidence,
                provenance=row.provenance_json,
                eligibility_status=row.eligibility_status,
            )
            for row in self._validated_membership_rows((await self._session.execute(statement)).all(), include_non_tradable=True)
        ]

    async def list_period_memberships(
        self, universe_name: str, start_date: date, end_date: date
    ) -> list[MembershipImportRecord]:
        statement = (
            select(Symbol.ticker, Symbol.name.label("security_name"),
                   Symbol.security_id.label("symbol_security_id"),
                   UniverseMembership.security_id, UniverseMembership.valid_from,
                   UniverseMembership.valid_to, UniverseMembership.source,
                   UniverseMembership.source_confidence,
                   UniverseMembership.provenance_json,
                   UniverseMembership.eligibility_status)
            .join(UniverseMembership, UniverseMembership.symbol_id == Symbol.id)
            .join(Universe, Universe.id == UniverseMembership.universe_id)
            .where(Universe.name == universe_name)
            .where(UniverseMembership.valid_from <= end_date)
            .where((UniverseMembership.valid_to.is_(None)) | (UniverseMembership.valid_to > start_date))
            .order_by(Symbol.ticker, UniverseMembership.valid_from)
        )
        rows = self._validated_membership_rows((await self._session.execute(statement)).all())
        return [MembershipImportRecord(
            security_id=row.security_id, ticker=row.ticker, security_name=row.security_name,
            valid_from=row.valid_from, valid_to=row.valid_to, source=row.source,
            source_confidence=row.source_confidence, provenance=row.provenance_json,
            eligibility_status=row.eligibility_status,
        ) for row in rows]

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
        by_ticker: dict[str, uuid.UUID] = {}
        for record in records:
            existing_security = by_ticker.setdefault(record.ticker, record.security_id)
            if existing_security != record.security_id:
                raise PITIdentityResolutionError(
                    f"ticker {record.ticker} is associated with multiple security_id values"
                )
        securities = {record.security_id: record.security_name for record in records}
        await self._session.execute(
            insert(Security).values([{"id": key, "name": value} for key, value in securities.items()])
            .on_conflict_do_nothing(index_elements=[Security.id])
        )
        tickers = sorted(by_ticker)
        await self._session.execute(
            insert(Symbol)
            .values(
                [
                    {"ticker": ticker, "security_id": by_ticker[ticker],
                     "asset_type": "stock", "metadata_json": {}}
                    for ticker in tickers
                ]
            )
            .on_conflict_do_nothing(index_elements=[Symbol.ticker])
        )
        symbol_rows = (
            await self._session.execute(
                select(Symbol.ticker, Symbol.id, Symbol.security_id).where(Symbol.ticker.in_(tickers))
            )
        ).all()
        for row in symbol_rows:
            expected = by_ticker[row.ticker]
            if row.security_id is not None and row.security_id != expected:
                raise PITIdentityResolutionError(
                    f"ticker {row.ticker} is already linked to a different security_id"
                )
            if row.security_id is None:
                await self._session.execute(update(Symbol).where(Symbol.id == row.id).values(security_id=expected))
        symbol_ids = {row.ticker: row.id for row in symbol_rows}
        values = [
            {
                "universe_id": universe_id,
                "symbol_id": symbol_ids[record.ticker],
                "security_id": record.security_id,
                "valid_from": record.valid_from,
                "valid_to": record.valid_to,
                "source": record.source,
                "source_confidence": record.source_confidence,
                "provenance_json": record.provenance,
                "eligibility_status": record.eligibility_status,
            }
            for record in records
        ]
        statement = insert(UniverseMembership).values(values)
        statement = statement.on_conflict_do_update(
            constraint="uq_universe_membership_security_identity",
            set_={"symbol_id": statement.excluded.symbol_id,
                  "valid_to": statement.excluded.valid_to,
                  "source_confidence": statement.excluded.source_confidence,
                  "provenance_json": statement.excluded.provenance_json,
                  "eligibility_status": statement.excluded.eligibility_status,
                  "loaded_at": func.now()},
        )
        result = await self._session.execute(statement)
        await self._session.commit()
        return result.rowcount or 0

    @staticmethod
    def _validated_membership_rows(rows, *, include_non_tradable: bool = False):
        validated = []
        for row in rows:
            status = row.eligibility_status
            if status == "EXPLICITLY_NON_TRADABLE_OR_INVALID":
                if include_non_tradable:
                    validated.append(row)
                continue
            if status != "ELIGIBLE":
                raise PITIdentityResolutionError(
                    f"PIT membership cannot be resolved safely (ticker={row.ticker}, status={status})"
                )
            if row.security_id is None:
                raise PITIdentityResolutionError(
                    f"PIT membership has no security_id (ticker={row.ticker})"
                )
            if row.symbol_security_id != row.security_id:
                raise PITIdentityResolutionError(
                    f"PIT symbol/security identity mismatch (ticker={row.ticker})"
                )
            validated.append(row)
        return validated


class PITIdentityResolutionError(RuntimeError):
    """Raised when PIT membership cannot be mapped without ticker-based inference."""


class OpportunityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, opportunities: list[OpportunityResult], configuration: dict) -> None:
        for item in opportunities:
            await self._session.execute(
                insert(Strategy).values(
                    name=item.strategy, version=item.strategy_version,
                    parameters=configuration.get("parameters", {}), description="Deterministic scanner strategy",
                ).on_conflict_do_nothing(constraint="uq_strategy_version")
            )
            strategy_id = await self._session.scalar(
                select(Strategy.id).where(Strategy.name == item.strategy, Strategy.version == item.strategy_version)
            )
            symbol_id = await self._session.scalar(select(Symbol.id).where(Symbol.ticker == item.ticker))
            if strategy_id is None or symbol_id is None:
                raise RuntimeError("opportunity references unresolved strategy or symbol")
            values = {
                "symbol_id": symbol_id, "strategy_id": strategy_id,
                "timestamp": datetime.combine(item.as_of_date, time.min, tzinfo=UTC),
                "pattern": item.strategy, "price": item.price, "score": item.score,
                "details": item.model_dump(mode="json"), "score_components": item.score_components,
                "universe": item.universe, "strategy_version": item.strategy_version,
                "configuration_hash": item.configuration_hash, "configuration": configuration,
                "data_provider": item.data_provider, "session_status": item.session_status,
                "executed_at": item.executed_at,
            }
            statement = insert(Opportunity).values(**values)
            statement = statement.on_conflict_do_update(
                constraint="uq_opportunity_identity",
                set_={key: value for key, value in values.items() if key not in {"symbol_id", "strategy_id", "timestamp", "configuration_hash"}},
            )
            await self._session.execute(statement)
        await self._session.commit()

    async def list(
        self, *, scan_date: date | None = None, ticker: str | None = None,
        strategy: str | None = None, universe: str | None = None,
        min_score: float | None = None, limit: int = 100, offset: int = 0,
    ) -> list[dict]:
        statement = select(Opportunity.details).join(Symbol).join(Strategy)
        if scan_date:
            statement = statement.where(func.date(Opportunity.timestamp) == scan_date)
        if ticker:
            statement = statement.where(Symbol.ticker == ticker.upper())
        if strategy:
            statement = statement.where(Strategy.name == strategy)
        if universe:
            statement = statement.where(Opportunity.universe == universe)
        if min_score is not None:
            statement = statement.where(Opportunity.score >= min_score)
        statement = statement.order_by(Opportunity.timestamp.desc(), Opportunity.score.desc(), Symbol.ticker).limit(limit).offset(offset)
        return list((await self._session.scalars(statement)).all())


class BacktestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, result: BacktestRunResult, configuration: dict) -> None:
        await self._session.execute(
            insert(Strategy).values(
                name=result.strategy, version=result.strategy_version,
                parameters=configuration.get("parameters", {}),
                description="Deterministic event-study strategy",
            ).on_conflict_do_nothing(constraint="uq_strategy_version")
        )
        strategy_id = await self._session.scalar(
            select(Strategy.id).where(Strategy.name == result.strategy,
                                      Strategy.version == result.strategy_version)
        )
        run_id = uuid.UUID(result.run_id)
        values = {
            "id": run_id, "strategy_id": strategy_id, "status": result.status,
            "started_at": result.created_at, "completed_at": datetime.now(UTC),
            "parameters": configuration, "metrics": result.statistics_by_horizon,
            "limitations": result.data_quality_warnings,
            "config_hash": result.config_hash, "universe_mode": result.universe_mode.value,
            "universe_identifier": result.universe_identifier,
            "start_date": result.start_date, "end_date": result.end_date,
            "entry_model": result.entry_model.value, "benchmark": result.benchmark,
            "event_count": result.event_count,
            "metadata_json": result.model_dump(mode="json"),
        }
        statement = insert(BacktestRun).values(**values).on_conflict_do_update(
            constraint="uq_backtest_run_config_hash",
            set_={key: value for key, value in values.items() if key not in {"id", "config_hash"}},
        )
        await self._session.execute(statement)
        await self._session.execute(sa_delete(BacktestEvent).where(BacktestEvent.backtest_run_id == run_id))
        tickers = {event.ticker for event in result.events}
        symbol_rows = (await self._session.execute(
            select(Symbol.ticker, Symbol.id).where(Symbol.ticker.in_(tickers))
        )).all() if tickers else []
        symbol_ids = {row.ticker: row.id for row in symbol_rows}
        for event in result.events:
            event_id = uuid.uuid5(run_id, f"{event.ticker}:{event.signal_date}")
            await self._session.execute(insert(BacktestEvent).values(
                id=event_id, backtest_run_id=run_id, symbol_id=symbol_ids[event.ticker],
                signal_date=event.signal_date, score=event.score,
                features=event.model_dump(mode="json", exclude={"outcomes"}),
                score_components=event.score_components,
                entry_model=event.entry_model.value, entry_date=event.entry_date,
                entry_price=event.entry_price,
            ))
            if event.outcomes:
                await self._session.execute(insert(BacktestForwardReturn).values([
                    {"backtest_event_id": event_id, **outcome.model_dump()}
                    for outcome in event.outcomes
                ]))
        await self._session.commit()

    async def get(self, run_id: uuid.UUID) -> dict | None:
        return await self._session.scalar(
            select(BacktestRun.metadata_json).where(BacktestRun.id == run_id)
        )

    async def list(self, limit: int = 100, offset: int = 0) -> list[dict]:
        statement = (select(BacktestRun.metadata_json)
                     .order_by(BacktestRun.created_at.desc()).limit(limit).offset(offset))
        return list((await self._session.scalars(statement)).all())


class ResearchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, result: ResearchResult, configuration: dict) -> None:
        run_id = uuid.UUID(result.run_id)
        values = {
            "id": run_id, "source_backtest_run_id": uuid.UUID(result.source_backtest_run_id),
            "research_type": result.research_type, "config_hash": result.config_hash,
            "event_count": result.event_count, "configuration": configuration,
            "strategy_version": result.strategy_version, "universe_mode": result.universe_mode,
            "start_date": result.start_date, "end_date": result.end_date,
            "results": result.model_dump(mode="json"),
        }
        await self._session.execute(insert(ResearchRun).values(**values).on_conflict_do_update(
            constraint="uq_research_run_config_hash",
            set_={key: value for key, value in values.items() if key not in {"id", "config_hash"}},
        ))
        await self._session.execute(sa_delete(MarketRegimeObservation).where(MarketRegimeObservation.research_run_id == run_id))
        observations = result.results.get("observations", [])
        if observations:
            tickers = {row["ticker"] for row in observations}
            symbol_rows = (await self._session.execute(select(Symbol.ticker, Symbol.id).where(Symbol.ticker.in_(tickers)))).all()
            symbol_ids = {row.ticker: row.id for row in symbol_rows}
            values = [{
                "research_run_id": run_id, "symbol_id": symbol_ids[row["ticker"]],
                "signal_date": date.fromisoformat(row["signal_date"]),
                "sma200_regime": row["sma200_regime"], "sma50_regime": row["sma50_regime"],
                "configuration": row["configuration"], "volatility_regime": row["volatility_regime"],
                "realized_volatility": row["realized_volatility"],
            } for row in observations]
            for batch in _chunks(values):
                await self._session.execute(insert(MarketRegimeObservation).values(batch))
        await self._session.commit()

    async def get(self, run_id: uuid.UUID) -> dict | None:
        return await self._session.scalar(select(ResearchRun.results).where(ResearchRun.id == run_id))

    async def list(self, limit: int = 100, offset: int = 0) -> list[dict]:
        statement = select(ResearchRun.results).order_by(ResearchRun.created_at.desc()).limit(limit).offset(offset)
        return list((await self._session.scalars(statement)).all())


class PortfolioRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, result: PortfolioSimulationResult) -> None:
        run_id = uuid.UUID(result.run_id)
        document = result.model_dump(mode="json")
        values = {
            "id": run_id, "source_backtest_run_id": uuid.UUID(result.source_backtest_run_id),
            "config_hash": result.config_hash, "strategy_version": result.strategy_version,
            "universe_mode": result.universe_mode,
            "start_date": result.start_date, "end_date": result.end_date,
            "configuration": result.configuration, "metrics": result.metrics,
            "benchmark_metrics": result.benchmark_metrics, "metadata_json": document,
        }
        await self._session.execute(insert(PortfolioSimulationRun).values(**values).on_conflict_do_update(
            constraint="uq_portfolio_simulation_config_hash",
            set_={key: value for key, value in values.items() if key not in {"id", "config_hash"}},
        ))
        for model in (PortfolioTradeRecord, PortfolioDailyEquity, PortfolioSkippedSignal):
            await self._session.execute(sa_delete(model).where(model.portfolio_run_id == run_id))
        tickers = {item.ticker for item in result.trades} | {item.ticker for item in result.skipped_signals}
        symbol_rows = (await self._session.execute(select(Symbol.ticker, Symbol.id).where(Symbol.ticker.in_(tickers)))).all() if tickers else []
        symbol_ids = {row.ticker: row.id for row in symbol_rows}
        def identity(item) -> dict[str, Any]:
            security_id = uuid.UUID(item.security_id) if item.security_id else None
            symbol_id = symbol_ids.get(item.ticker)
            if security_id is None and symbol_id is None:
                raise ValueError(f"portfolio ledger identity unresolved: {item.ticker}")
            return {"security_id": security_id, "symbol_id": symbol_id}
        if result.trades:
            values = [{
                "portfolio_run_id": run_id, **identity(item),
                "signal_date": item.signal_date, "entry_date": item.entry_date,
                "exit_date": item.exit_date, "score": item.score,
                "details": item.model_dump(mode="json"),
            } for item in result.trades]
            for batch in _chunks(values):
                await self._session.execute(insert(PortfolioTradeRecord).values(batch))
        if result.daily_equity:
            values = [{
                "portfolio_run_id": run_id, "session_date": item.session_date,
                "details": item.model_dump(mode="json"),
            } for item in result.daily_equity]
            for batch in _chunks(values):
                await self._session.execute(insert(PortfolioDailyEquity).values(batch))
        if result.skipped_signals:
            values = [{
                "portfolio_run_id": run_id, **identity(item),
                "signal_date": item.signal_date, "reason": item.reason,
                "details": item.model_dump(mode="json"),
            } for item in result.skipped_signals]
            for batch in _chunks(values):
                await self._session.execute(insert(PortfolioSkippedSignal).values(batch))
        await self._session.commit()

    async def get(self, run_id: uuid.UUID) -> dict | None:
        return await self._session.scalar(select(PortfolioSimulationRun.metadata_json).where(PortfolioSimulationRun.id == run_id))

    async def list(self, limit: int = 100, offset: int = 0) -> list[dict]:
        statement = select(PortfolioSimulationRun.metadata_json).order_by(PortfolioSimulationRun.created_at.desc()).limit(limit).offset(offset)
        return list((await self._session.scalars(statement)).all())
