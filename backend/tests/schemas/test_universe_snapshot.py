from datetime import date

import pytest
from pydantic import ValidationError

from app.schemas.universe import CurrentSnapshotImport


def test_current_snapshot_normalizes_and_deduplicates_tickers() -> None:
    snapshot = CurrentSnapshotImport(
        tickers=[" msft ", "AAPL", "MSFT"],
        snapshot_date=date(2026, 9, 23), source="source-v1",
    )
    assert snapshot.tickers == ["AAPL", "MSFT"]


def test_current_snapshot_requires_source_and_members() -> None:
    with pytest.raises(ValidationError):
        CurrentSnapshotImport(tickers=[], snapshot_date=date(2026, 9, 23), source="")
