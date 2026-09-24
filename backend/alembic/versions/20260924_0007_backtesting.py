"""Add reproducible event-study backtesting tables."""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260924_0007"
down_revision: str | None = "20260923_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("backtest_runs", sa.Column("config_hash", sa.String(64)))
    op.add_column("backtest_runs", sa.Column("universe_mode", sa.String(32)))
    op.add_column("backtest_runs", sa.Column("universe_identifier", sa.String(64)))
    op.add_column("backtest_runs", sa.Column("start_date", sa.Date()))
    op.add_column("backtest_runs", sa.Column("end_date", sa.Date()))
    op.add_column("backtest_runs", sa.Column("entry_model", sa.String(32)))
    op.add_column("backtest_runs", sa.Column("benchmark", sa.String(16)))
    op.add_column("backtest_runs", sa.Column("event_count", sa.Integer(), server_default="0", nullable=False))
    op.add_column("backtest_runs", sa.Column("metadata_json", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False))
    op.create_index("ix_backtest_runs_config_hash", "backtest_runs", ["config_hash"])
    op.create_unique_constraint("uq_backtest_run_config_hash", "backtest_runs", ["config_hash"])
    op.create_table(
        "backtest_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("backtest_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("backtest_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("symbol_id", sa.Integer(), sa.ForeignKey("symbols.id"), nullable=False),
        sa.Column("signal_date", sa.Date(), nullable=False),
        sa.Column("score", sa.Numeric(8, 4), nullable=False),
        sa.Column("features", sa.JSON(), nullable=False),
        sa.Column("score_components", sa.JSON(), nullable=False),
        sa.Column("entry_model", sa.String(32), nullable=False),
        sa.Column("entry_date", sa.Date()),
        sa.Column("entry_price", sa.Numeric(20, 8)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("backtest_run_id", "symbol_id", "signal_date", name="uq_backtest_event_identity"),
    )
    op.create_index("ix_backtest_events_run_signal", "backtest_events", ["backtest_run_id", "signal_date"])
    op.create_table(
        "backtest_forward_returns",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("backtest_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("backtest_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("horizon", sa.Integer(), nullable=False),
        sa.Column("stock_return", sa.Numeric(16, 10)),
        sa.Column("benchmark_return", sa.Numeric(16, 10)),
        sa.Column("excess_return", sa.Numeric(16, 10)),
        sa.Column("mfe", sa.Numeric(16, 10)),
        sa.Column("mae", sa.Numeric(16, 10)),
        sa.Column("forward_data_complete", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("backtest_event_id", "horizon", name="uq_backtest_forward_horizon"),
    )
    op.create_index("ix_backtest_forward_event_horizon", "backtest_forward_returns", ["backtest_event_id", "horizon"])


def downgrade() -> None:
    op.drop_table("backtest_forward_returns")
    op.drop_table("backtest_events")
    op.drop_constraint("uq_backtest_run_config_hash", "backtest_runs", type_="unique")
    op.drop_index("ix_backtest_runs_config_hash", table_name="backtest_runs")
    for column in ("metadata_json", "event_count", "benchmark", "entry_model", "end_date", "start_date", "universe_identifier", "universe_mode", "config_hash"):
        op.drop_column("backtest_runs", column)
