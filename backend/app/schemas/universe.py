import re
from datetime import date

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9.-]{0,14}$")


class MembershipImportRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticker: str
    valid_from: date
    valid_to: date | None = None
    source: str

    @field_validator("ticker")
    @classmethod
    def validate_ticker(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not TICKER_PATTERN.fullmatch(normalized):
            raise ValueError("ticker has an invalid format")
        return normalized

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("source is required")
        return normalized

    @model_validator(mode="after")
    def validate_interval(self) -> "MembershipImportRecord":
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("valid_to must be on or after valid_from")
        return self


class CurrentSnapshotImport(BaseModel):
    model_config = ConfigDict(frozen=True)
    tickers: list[str]
    snapshot_date: date
    source: str

    @field_validator("tickers")
    @classmethod
    def validate_tickers(cls, values: list[str]) -> list[str]:
        normalized = []
        for value in values:
            ticker = value.strip().upper()
            if not TICKER_PATTERN.fullmatch(ticker):
                raise ValueError(f"invalid ticker: {value}")
            normalized.append(ticker)
        if not normalized:
            raise ValueError("at least one ticker is required")
        return sorted(set(normalized))

    @field_validator("source")
    @classmethod
    def require_source(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("source is required")
        return value.strip()
