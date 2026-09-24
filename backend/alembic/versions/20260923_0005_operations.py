"""Separate current snapshots from historical memberships."""
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "20260923_0005"
down_revision: str | None = "20260923_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "universe_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("universe_id", sa.Integer(), sa.ForeignKey("universes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(255), nullable=False),
        sa.Column("loaded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("universe_id", "snapshot_date", "source", name="uq_universe_snapshot_identity"),
    )
    op.create_table(
        "universe_snapshot_members",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("snapshot_id", sa.BigInteger(), sa.ForeignKey("universe_snapshots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("symbol_id", sa.Integer(), sa.ForeignKey("symbols.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("snapshot_id", "symbol_id", name="uq_universe_snapshot_member"),
    )


def downgrade() -> None:
    op.drop_table("universe_snapshot_members")
    op.drop_table("universe_snapshots")
