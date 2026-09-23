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
