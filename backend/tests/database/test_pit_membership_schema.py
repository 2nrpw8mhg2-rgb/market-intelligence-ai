import uuid

import pytest
from pydantic import ValidationError

from app.models import UniverseMembership
from app.schemas.universe import MembershipImportRecord


def test_membership_schema_is_security_id_native_and_preserves_evidence() -> None:
    columns = UniverseMembership.__table__.columns
    assert {"security_id", "source_confidence", "provenance_json", "eligibility_status"} <= set(columns.keys())
    constraints = {item.name for item in UniverseMembership.__table__.constraints}
    assert "uq_universe_membership_security_identity" in constraints


def test_membership_import_cannot_be_ticker_only() -> None:
    with pytest.raises(ValidationError, match="security_id"):
        MembershipImportRecord(
            ticker="AAPL", valid_from="2025-01-01", source="test",
            source_confidence="HIGH", provenance={"source": "fixture"},
        )


def test_membership_requires_provenance() -> None:
    with pytest.raises(ValidationError, match="provenance"):
        MembershipImportRecord(
            security_id=uuid.UUID(int=1), ticker="AAPL", valid_from="2025-01-01",
            source="test", source_confidence="HIGH", provenance={},
        )
