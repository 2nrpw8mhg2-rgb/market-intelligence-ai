"""Add membership provenance timestamp and stable security identity."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260923_0003"
down_revision: str | None = "20260923_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "securities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255)),
        sa.Column("cik", sa.String(16)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("cik", name="uq_securities_cik"),
    )
    op.add_column(
        "symbols", sa.Column("security_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_foreign_key(
        "fk_symbols_security_id_securities", "symbols", "securities", ["security_id"], ["id"]
    )
    op.create_index("ix_symbols_security_id", "symbols", ["security_id"])
    op.add_column(
        "universe_memberships",
        sa.Column(
            "loaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("universe_memberships", "loaded_at")
    op.drop_index("ix_symbols_security_id", table_name="symbols")
    op.drop_constraint("fk_symbols_security_id_securities", "symbols", type_="foreignkey")
    op.drop_column("symbols", "security_id")
    op.drop_table("securities")
