from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class FeatureSeriesResponse(BaseModel):
    ticker: str
    start_date: date | None
    end_date: date | None
    count: int = Field(ge=0)
    rows: list[dict[str, Any]]


def serialize_feature_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for record in records:
        row: dict[str, Any] = {}
        for key, value in record.items():
            if isinstance(value, datetime):
                row[key] = value.isoformat()
            elif value is None or value != value:
                row[key] = None
            elif hasattr(value, "item"):
                row[key] = value.item()
            else:
                row[key] = value
        serialized.append(row)
    return serialized
