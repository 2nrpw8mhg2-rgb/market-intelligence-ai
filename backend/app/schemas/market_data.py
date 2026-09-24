from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator


class MarketBar(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticker: str = Field(min_length=1, max_length=16)
    timestamp: datetime
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    # Split-adjusted aggregates can contain fractional share volume.
    volume: float = Field(ge=0)

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("timestamp")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_price_range(self) -> "MarketBar":
        if self.low > self.high:
            raise ValueError("low cannot exceed high")
        if not self.low <= self.open <= self.high:
            raise ValueError("open must be within the low/high range")
        if not self.low <= self.close <= self.high:
            raise ValueError("close must be within the low/high range")
        return self
