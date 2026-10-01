"""make portfolio ledgers security-id native

Revision ID: 20261001_0010
Revises: 20260928_0009
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20261001_0010"
down_revision = "20260928_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("portfolio_trades", "portfolio_skipped_signals"):
        op.add_column(
            table,
            sa.Column("security_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.create_foreign_key(
            f"fk_{table}_security_id", table, "securities", ["security_id"], ["id"]
        )
        op.create_index(f"ix_{table}_security_id", table, ["security_id"])
        op.execute(sa.text(
            f"UPDATE {table} AS ledger SET security_id = symbol.security_id "
            f"FROM symbols AS symbol WHERE ledger.symbol_id = symbol.id"
        ))
        op.alter_column(table, "symbol_id", existing_type=sa.Integer(), nullable=True)
    op.create_check_constraint(
        "ck_portfolio_trade_identity", "portfolio_trades",
        "symbol_id IS NOT NULL OR security_id IS NOT NULL",
    )
    op.create_check_constraint(
        "ck_portfolio_skipped_identity", "portfolio_skipped_signals",
        "symbol_id IS NOT NULL OR security_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_portfolio_skipped_identity", "portfolio_skipped_signals", type_="check")
    op.drop_constraint("ck_portfolio_trade_identity", "portfolio_trades", type_="check")
    for table in ("portfolio_skipped_signals", "portfolio_trades"):
        op.execute(sa.text(
            f"UPDATE {table} AS ledger SET symbol_id = symbol.id "
            f"FROM symbols AS symbol WHERE ledger.symbol_id IS NULL "
            f"AND ledger.security_id = symbol.security_id"
        ))
        op.alter_column(table, "symbol_id", existing_type=sa.Integer(), nullable=False)
        op.drop_index(f"ix_{table}_security_id", table_name=table)
        op.drop_constraint(f"fk_{table}_security_id", table, type_="foreignkey")
        op.drop_column(table, "security_id")
