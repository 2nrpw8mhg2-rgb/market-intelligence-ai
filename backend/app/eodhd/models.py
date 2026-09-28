from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator


class HistoricalConstituent(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)
    code: str = Field(alias="Code")
    name: str = Field(alias="Name")
    start_date: date | None = Field(default=None, alias="StartDate")
    end_date: date | None = Field(default=None, alias="EndDate")
    is_active_now: bool = Field(alias="IsActiveNow")
    is_delisted: bool = Field(alias="IsDelisted")

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        value = value.strip().upper()
        if not value:
            raise ValueError("constituent code cannot be empty")
        return value

    def is_member_on(self, session: date, *, end_date_inclusive: bool = True) -> bool:
        if self.start_date is not None and session < self.start_date:
            return False
        if self.end_date is None:
            return True
        return session <= self.end_date if end_date_inclusive else session < self.end_date


class EODBar(BaseModel):
    model_config = ConfigDict(extra="ignore")
    date: date
    open: float
    high: float
    low: float
    close: float
    adjusted_close: float
    volume: float = Field(ge=0)


class SymbolChange(BaseModel):
    model_config = ConfigDict(extra="ignore")
    exchange: str
    old_symbol: str
    new_symbol: str
    company_name: str
    effective: date

    @field_validator("old_symbol", "new_symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()


class CorporateAction(BaseModel):
    model_config = ConfigDict(extra="allow")
    date: date
    split: str | None = None
    value: float | None = None
    unadjustedValue: float | None = None
    declarationDate: date | None = None
    recordDate: date | None = None
    paymentDate: date | None = None
    currency: str | None = None


def parse_split_factor(value: str) -> float:
    parts = value.split("/")
    if len(parts) != 2:
        raise ValueError(f"invalid EODHD split ratio: {value}")
    numerator, denominator = (float(part) for part in parts)
    if numerator <= 0 or denominator <= 0:
        raise ValueError("split ratio values must be positive")
    return numerator / denominator


def build_membership_snapshot(
    records: list[HistoricalConstituent], as_of: date, *, end_date_inclusive: bool = True,
) -> list[HistoricalConstituent]:
    return sorted(
        (item for item in records if item.is_member_on(as_of, end_date_inclusive=end_date_inclusive)),
        key=lambda item: item.code,
    )
