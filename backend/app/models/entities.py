import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, BigInteger, Date, DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin


class Symbol(TimestampMixin, Base):
    __tablename__ = "symbols"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    exchange: Mapped[str | None] = mapped_column(String(32))
    asset_type: Mapped[str] = mapped_column(String(32), default="stock")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class MarketBarRecord(TimestampMixin, Base):
    __tablename__ = "market_bars"
    __table_args__ = (
        UniqueConstraint(
            "symbol_id",
            "timestamp",
            "timeframe",
            "provider",
            name="uq_market_bars_identity",
        ),
        Index("ix_market_bars_symbol_timestamp", "symbol_id", "timestamp"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol_id: Mapped[int] = mapped_column(ForeignKey("symbols.id", ondelete="CASCADE"))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    timeframe: Mapped[str] = mapped_column(String(16), default="1d")
    open: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    high: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    low: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    close: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    volume: Mapped[int] = mapped_column(BigInteger)
    provider: Mapped[str] = mapped_column(String(32))


class Universe(TimestampMixin, Base):
    __tablename__ = "universes"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String(255))


class UniverseMembership(TimestampMixin, Base):
    __tablename__ = "universe_memberships"
    __table_args__ = (
        UniqueConstraint(
            "universe_id",
            "symbol_id",
            "valid_from",
            "source",
            name="uq_universe_membership_identity",
        ),
        Index(
            "ix_universe_membership_period",
            "universe_id",
            "valid_from",
            "valid_to",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    universe_id: Mapped[int] = mapped_column(ForeignKey("universes.id", ondelete="CASCADE"))
    symbol_id: Mapped[int] = mapped_column(ForeignKey("symbols.id", ondelete="CASCADE"))
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(255))


class Feature(TimestampMixin, Base):
    __tablename__ = "features"
    __table_args__ = (
        UniqueConstraint("symbol_id", "timestamp", "feature_set_version"),
        Index("ix_features_symbol_timestamp", "symbol_id", "timestamp"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol_id: Mapped[int] = mapped_column(ForeignKey("symbols.id", ondelete="CASCADE"))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    feature_set_version: Mapped[str] = mapped_column(String(32))
    values: Mapped[dict[str, Any]] = mapped_column(JSON)


class Strategy(TimestampMixin, Base):
    __tablename__ = "strategies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    version: Mapped[str] = mapped_column(String(32))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    description: Mapped[str | None] = mapped_column(Text)


class Opportunity(TimestampMixin, Base):
    __tablename__ = "opportunities"
    __table_args__ = (Index("ix_opportunities_symbol_timestamp", "symbol_id", "timestamp"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol_id: Mapped[int] = mapped_column(ForeignKey("symbols.id", ondelete="CASCADE"))
    strategy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("strategies.id"))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    pattern: Mapped[str] = mapped_column(String(64))
    price: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    score: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    score_components: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class BacktestRun(TimestampMixin, Base):
    __tablename__ = "backtest_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    strategy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("strategies.id"))
    status: Mapped[str] = mapped_column(String(32), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    limitations: Mapped[list[str]] = mapped_column(JSON, default=list)


class BacktestTrade(TimestampMixin, Base):
    __tablename__ = "backtest_trades"
    __table_args__ = (Index("ix_backtest_trades_run_entry", "backtest_run_id", "entry_timestamp"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    backtest_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("backtest_runs.id", ondelete="CASCADE"))
    symbol_id: Mapped[int] = mapped_column(ForeignKey("symbols.id"))
    entry_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    exit_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    entry_price: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    exit_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    pnl: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    return_pct: Mapped[Decimal | None] = mapped_column(Numeric(12, 8))
    exit_reason: Mapped[str | None] = mapped_column(String(64))
