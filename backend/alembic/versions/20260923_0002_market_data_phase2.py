"""Add point-in-time universes and provider-aware bar identity."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260923_0002"
down_revision: str | None = "20260923_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_market_bars_symbol_id", "market_bars", type_="unique")
    op.create_unique_constraint(
        "uq_market_bars_identity",
        "market_bars",
        ["symbol_id", "timestamp", "timeframe", "provider"],
    )
    op.create_table(
        "universes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(32), nullable=False),
        sa.Column("description", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("name", name="uq_universes_name"),
    )
    op.create_index("ix_universes_name", "universes", ["name"])
    op.create_table(
        "universe_memberships",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("universe_id", sa.Integer(), sa.ForeignKey("universes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("symbol_id", sa.Integer(), sa.ForeignKey("symbols.id", ondelete="CASCADE"), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date()),
        sa.Column("source", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "universe_id",
            "symbol_id",
            "valid_from",
            "source",
            name="uq_universe_membership_identity",
        ),
    )
    op.create_index(
        "ix_universe_membership_period",
        "universe_memberships",
        ["universe_id", "valid_from", "valid_to"],
    )


def downgrade() -> None:
    op.drop_table("universe_memberships")
    op.drop_table("universes")
    op.drop_constraint("uq_market_bars_identity", "market_bars", type_="unique")
    op.create_unique_constraint(
        "uq_market_bars_symbol_id",
        "market_bars",
        ["symbol_id", "timestamp", "timeframe"],
    )
