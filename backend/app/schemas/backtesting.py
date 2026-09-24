from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.scanner import BreakoutStrategyParameters


FIXED_UNIVERSE_WARNING = (
    "Fixed-universe research. Results may contain survivorship bias and must not "
    "be interpreted as a point-in-time S&P 500 backtest."
)
HORIZONS = (1, 5, 10, 20, 60)


class UniverseMode(StrEnum):
    POINT_IN_TIME = "POINT_IN_TIME"
    FIXED_UNIVERSE_RESEARCH = "FIXED_UNIVERSE_RESEARCH"


class EntryModel(StrEnum):
    SIGNAL_CLOSE = "SIGNAL_CLOSE"
    NEXT_OPEN = "NEXT_OPEN"


class BacktestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strategy: Literal["BREAKOUT_20D_VOLUME"] = "BREAKOUT_20D_VOLUME"
    universe_mode: UniverseMode
    universe_identifier: str = "SP500"
    tickers: list[str] | None = None
    start_date: date
    end_date: date
    entry_model: EntryModel = EntryModel.NEXT_OPEN
    benchmark: str = "SPY"
    provider: Literal["massive"] = "massive"
    parameters: BreakoutStrategyParameters = Field(default_factory=BreakoutStrategyParameters)
    score_buckets: tuple[float, ...] = (0, 20, 40, 60, 80, 100)

    @model_validator(mode="after")
    def validate_request(self) -> "BacktestRequest":
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        if len(self.score_buckets) < 2 or tuple(sorted(set(self.score_buckets))) != self.score_buckets:
            raise ValueError("score_buckets must be strictly increasing")
        if self.score_buckets[0] > 0 or self.score_buckets[-1] < 100:
            raise ValueError("score_buckets must cover 0 through 100")
        return self


class ForwardOutcome(BaseModel):
    horizon: int
    stock_return: float | None
    benchmark_return: float | None
    excess_return: float | None
    mfe: float | None = None
    mae: float | None = None
    forward_data_complete: bool


class BacktestEventResult(BaseModel):
    ticker: str
    signal_date: date
    strategy: str
    strategy_version: str
    universe_mode: UniverseMode
    universe_identifier: str
    close: float
    previous_high_20d: float
    breakout_pct: float
    relative_volume: float
    sma_50: float
    sma_200: float
    momentum_20d: float
    avg_dollar_volume_20d: float
    distance_from_sma50: float
    score: float
    score_components: dict[str, float]
    entry_model: EntryModel
    entry_date: date | None
    entry_price: float | None
    outcomes: list[ForwardOutcome]


class BacktestRunResult(BaseModel):
    run_id: str
    status: Literal["COMPLETED", "DATA_UNAVAILABLE", "DRY_RUN"]
    config_hash: str
    strategy: str
    strategy_version: str
    universe_mode: UniverseMode
    universe_identifier: str
    survivorship_bias_warning: str | None
    start_date: date
    end_date: date
    entry_model: EntryModel
    benchmark: str
    event_count: int
    data_coverage: dict[str, Any]
    statistics_by_horizon: dict[str, Any]
    statistics_by_score_bucket: dict[str, Any]
    statistics_by_year: dict[str, Any]
    statistics_by_quarter: dict[str, Any]
    statistics_by_characteristic: dict[str, Any]
    events: list[BacktestEventResult]
    data_quality_warnings: list[str]
    created_at: datetime
