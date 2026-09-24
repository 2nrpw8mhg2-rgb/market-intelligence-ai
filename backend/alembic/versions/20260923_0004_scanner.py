"""Make opportunities reproducible and idempotent."""
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "20260923_0004"
down_revision: str | None = "20260923_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_strategies_name", "strategies", type_="unique")
    op.create_unique_constraint("uq_strategy_version", "strategies", ["name", "version"])
    for name, type_ in (
        ("universe", sa.String(32)), ("strategy_version", sa.String(32)),
        ("configuration_hash", sa.String(64)), ("data_provider", sa.String(32)),
        ("session_status", sa.String(32)),
    ):
        op.add_column("opportunities", sa.Column(name, type_, nullable=True))
    op.add_column("opportunities", sa.Column("configuration", sa.JSON(), nullable=True))
    op.add_column("opportunities", sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE opportunities SET universe='UNKNOWN', strategy_version='legacy', configuration_hash=md5(id::text), data_provider='unknown', session_status='UNKNOWN', configuration='{}'::json, executed_at=created_at")
    for name in (
        "universe", "strategy_version", "configuration_hash", "data_provider",
        "session_status", "configuration", "executed_at",
    ):
        op.alter_column("opportunities", name, nullable=False)
    op.create_unique_constraint(
        "uq_opportunity_identity", "opportunities",
        ["symbol_id", "timestamp", "strategy_id", "configuration_hash"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_opportunity_identity", "opportunities", type_="unique")
    for name in ("executed_at", "configuration", "session_status", "data_provider", "configuration_hash", "strategy_version", "universe"):
        op.drop_column("opportunities", name)
    op.drop_constraint("uq_strategy_version", "strategies", type_="unique")
    op.create_unique_constraint("uq_strategies_name", "strategies", ["name"])
