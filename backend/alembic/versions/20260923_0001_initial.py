"""Create initial quantitative research schema."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260923_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "symbols",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticker", sa.String(16), nullable=False),
        sa.Column("name", sa.String(255)),
        sa.Column("exchange", sa.String(32)),
        sa.Column("asset_type", sa.String(32), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("ticker", name="uq_symbols_ticker"),
    )
    op.create_index("ix_symbols_ticker", "symbols", ["ticker"])
    op.create_table(
        "strategies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "market_bars",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("symbol_id", sa.Integer(), sa.ForeignKey("symbols.id", ondelete="CASCADE"), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timeframe", sa.String(16), nullable=False),
        sa.Column("open", sa.Numeric(20, 8), nullable=False),
        sa.Column("high", sa.Numeric(20, 8), nullable=False),
        sa.Column("low", sa.Numeric(20, 8), nullable=False),
        sa.Column("close", sa.Numeric(20, 8), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("symbol_id", "timestamp", "timeframe", name="uq_market_bars_symbol_id"),
    )
    op.create_index("ix_market_bars_symbol_timestamp", "market_bars", ["symbol_id", "timestamp"])
    op.create_table(
        "features",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("symbol_id", sa.Integer(), sa.ForeignKey("symbols.id", ondelete="CASCADE"), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("feature_set_version", sa.String(32), nullable=False),
        sa.Column("values", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("symbol_id", "timestamp", "feature_set_version", name="uq_features_symbol_id"),
    )
    op.create_index("ix_features_symbol_timestamp", "features", ["symbol_id", "timestamp"])
    op.create_table(
        "opportunities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("symbol_id", sa.Integer(), sa.ForeignKey("symbols.id", ondelete="CASCADE"), nullable=False),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("strategies.id"), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pattern", sa.String(64), nullable=False),
        sa.Column("price", sa.Numeric(20, 8), nullable=False),
        sa.Column("score", sa.Numeric(6, 3)),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("score_components", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_opportunities_symbol_timestamp", "opportunities", ["symbol_id", "timestamp"])
    op.create_table(
        "backtest_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("strategies.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("limitations", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_backtest_runs_status", "backtest_runs", ["status"])
    op.create_table(
        "backtest_trades",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("backtest_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("backtest_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("symbol_id", sa.Integer(), sa.ForeignKey("symbols.id"), nullable=False),
        sa.Column("entry_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exit_timestamp", sa.DateTime(timezone=True)),
        sa.Column("entry_price", sa.Numeric(20, 8), nullable=False),
        sa.Column("exit_price", sa.Numeric(20, 8)),
        sa.Column("quantity", sa.Numeric(20, 8), nullable=False),
        sa.Column("pnl", sa.Numeric(20, 8)),
        sa.Column("return_pct", sa.Numeric(12, 8)),
        sa.Column("exit_reason", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_backtest_trades_run_entry", "backtest_trades", ["backtest_run_id", "entry_timestamp"])


def downgrade() -> None:
    for table in (
        "backtest_trades",
        "backtest_runs",
        "opportunities",
        "features",
        "market_bars",
        "strategies",
        "symbols",
    ):
        op.drop_table(table)
