"""make PIT universe membership security-id native

Revision ID: 20260928_0009
Revises: 20260924_0008
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260928_0009"
down_revision = "20260924_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("universe_memberships", sa.Column("security_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("universe_memberships", sa.Column("source_confidence", sa.String(16), nullable=False, server_default="UNRESOLVED"))
    op.add_column("universe_memberships", sa.Column("provenance_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")))
    op.add_column("universe_memberships", sa.Column("eligibility_status", sa.String(48), nullable=False, server_default="UNRESOLVED"))
    op.create_foreign_key("fk_universe_memberships_security_id", "universe_memberships", "securities", ["security_id"], ["id"])
    op.execute("""
        UPDATE universe_memberships AS membership
        SET security_id = symbol.security_id,
            eligibility_status = CASE WHEN symbol.security_id IS NULL THEN 'UNRESOLVED' ELSE 'ELIGIBLE' END,
            provenance_json = json_build_object('migration', '20260928_0009', 'legacy_symbol_id', membership.symbol_id)
        FROM symbols AS symbol WHERE symbol.id = membership.symbol_id
    """)
    op.drop_constraint("uq_universe_membership_identity", "universe_memberships", type_="unique")
    op.create_unique_constraint("uq_universe_membership_security_identity", "universe_memberships", ["universe_id", "security_id", "valid_from", "source"])
    op.create_index("ix_universe_membership_security_period", "universe_memberships", ["universe_id", "security_id", "valid_from", "valid_to"])


def downgrade() -> None:
    op.drop_index("ix_universe_membership_security_period", table_name="universe_memberships")
    op.drop_constraint("uq_universe_membership_security_identity", "universe_memberships", type_="unique")
    op.create_unique_constraint("uq_universe_membership_identity", "universe_memberships", ["universe_id", "symbol_id", "valid_from", "source"])
    op.drop_constraint("fk_universe_memberships_security_id", "universe_memberships", type_="foreignkey")
    op.drop_column("universe_memberships", "eligibility_status")
    op.drop_column("universe_memberships", "provenance_json")
    op.drop_column("universe_memberships", "source_confidence")
    op.drop_column("universe_memberships", "security_id")
