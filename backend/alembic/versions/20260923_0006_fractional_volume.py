"""Preserve fractional volume returned by adjusted Massive aggregates."""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260923_0006"
down_revision: str | None = "20260923_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "market_bars", "volume",
        existing_type=sa.BigInteger(), type_=sa.Numeric(24, 6),
        existing_nullable=False, postgresql_using="volume::numeric(24, 6)",
    )


def downgrade() -> None:
    op.alter_column(
        "market_bars", "volume",
        existing_type=sa.Numeric(24, 6), type_=sa.BigInteger(),
        existing_nullable=False, postgresql_using="round(volume)::bigint",
    )
