"""Add Phase 6 research and portfolio simulation persistence."""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260924_0008"
down_revision: str | None = "20260924_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "research_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_backtest_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("backtest_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("research_type", sa.String(64), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("strategy_version", sa.String(32), nullable=False),
        sa.Column("universe_mode", sa.String(32), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("results", sa.JSON(), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("config_hash", name="uq_research_run_config_hash"),
    )
    op.create_index("ix_research_runs_source_backtest_run_id", "research_runs", ["source_backtest_run_id"])
    op.create_index("ix_research_runs_research_type", "research_runs", ["research_type"])
    op.create_index("ix_research_runs_config_hash", "research_runs", ["config_hash"])
    op.create_table(
        "market_regime_observations",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("research_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("research_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("symbol_id", sa.Integer(), sa.ForeignKey("symbols.id"), nullable=False),
        sa.Column("signal_date", sa.Date(), nullable=False),
        sa.Column("sma200_regime", sa.String(40), nullable=False),
        sa.Column("sma50_regime", sa.String(40), nullable=False),
        sa.Column("configuration", sa.String(40), nullable=False),
        sa.Column("volatility_regime", sa.String(40), nullable=False),
        sa.Column("realized_volatility", sa.Numeric(16, 10)),
        *timestamps(),
        sa.UniqueConstraint("research_run_id", "symbol_id", "signal_date", name="uq_market_regime_observation"),
    )
    op.create_index("ix_market_regime_run_date", "market_regime_observations", ["research_run_id", "signal_date"])

    op.create_table(
        "portfolio_simulation_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_backtest_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("backtest_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("strategy_version", sa.String(32), nullable=False),
        sa.Column("universe_mode", sa.String(32), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("benchmark_metrics", sa.JSON(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("config_hash", name="uq_portfolio_simulation_config_hash"),
    )
    op.create_index("ix_portfolio_simulation_runs_source_backtest_run_id", "portfolio_simulation_runs", ["source_backtest_run_id"])
    op.create_index("ix_portfolio_simulation_runs_config_hash", "portfolio_simulation_runs", ["config_hash"])
    op.create_table(
        "portfolio_trades",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("portfolio_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("portfolio_simulation_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("symbol_id", sa.Integer(), sa.ForeignKey("symbols.id"), nullable=False),
        sa.Column("signal_date", sa.Date(), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("exit_date", sa.Date(), nullable=False),
        sa.Column("score", sa.Numeric(8, 4), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        *timestamps(),
    )
    op.create_index("ix_portfolio_trades_run_entry", "portfolio_trades", ["portfolio_run_id", "entry_date"])
    op.create_table(
        "portfolio_daily_equity",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("portfolio_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("portfolio_simulation_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("portfolio_run_id", "session_date", name="uq_portfolio_daily_equity"),
    )
    op.create_table(
        "portfolio_skipped_signals",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("portfolio_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("portfolio_simulation_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("symbol_id", sa.Integer(), sa.ForeignKey("symbols.id"), nullable=False),
        sa.Column("signal_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.String(64), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        *timestamps(),
    )
    op.create_index("ix_portfolio_skipped_run_reason", "portfolio_skipped_signals", ["portfolio_run_id", "reason"])


def downgrade() -> None:
    op.drop_table("portfolio_skipped_signals")
    op.drop_table("portfolio_daily_equity")
    op.drop_table("portfolio_trades")
    op.drop_table("portfolio_simulation_runs")
    op.drop_table("market_regime_observations")
    op.drop_table("research_runs")
