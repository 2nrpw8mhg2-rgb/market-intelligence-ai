from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ScanMode(StrEnum):
    LATEST = "LATEST"
    HISTORICAL = "HISTORICAL"


class BreakoutStrategyParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    breakout_lookback: Literal[20] = 20
    min_relative_volume: float = Field(default=1.5, gt=0)
    trend_sma_short: Literal[50] = 50
    trend_sma_long: Literal[200] = 200
    min_avg_dollar_volume: float = Field(default=10_000_000, gt=0)
    min_price: float = Field(default=5, gt=0)


class ScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strategy: Literal["BREAKOUT_20D_VOLUME"] = "BREAKOUT_20D_VOLUME"
    universe: Literal["SP500"] = "SP500"
    mode: ScanMode = ScanMode.LATEST
    as_of_date: date | None = None
    parameters: BreakoutStrategyParameters = Field(default_factory=BreakoutStrategyParameters)

    @model_validator(mode="after")
    def validate_mode(self) -> "ScanRequest":
        if self.mode is ScanMode.HISTORICAL and self.as_of_date is None:
            raise ValueError("as_of_date is required for HISTORICAL mode")
        return self


class ScoreResult(BaseModel):
    score: float = Field(ge=0, le=100)
    components: dict[str, float]


class BreakoutEvidence(BaseModel):
    previous_high: float
    current_close: float
    breakout_pct: float
    condition_passed: bool


class VolumeEvidence(BaseModel):
    relative_volume: float
    average_volume_20d: float
    current_volume: float
    minimum_relative_volume: float
    condition_passed: bool


class TrendEvidence(BaseModel):
    close: float
    sma_50: float
    sma_200: float
    above_sma_50: bool
    sma_50_above_sma_200: bool


class LiquidityEvidence(BaseModel):
    avg_dollar_volume_20d: float
    minimum_required: float
    condition_passed: bool


class OpportunityExplanation(BaseModel):
    summary: str
    breakout: BreakoutEvidence
    volume: VolumeEvidence
    trend: TrendEvidence
    liquidity: LiquidityEvidence
    score_explanation: dict[str, float]


class OpportunityResult(BaseModel):
    ticker: str
    as_of_date: date
    strategy: str
    strategy_version: str
    universe: str
    price: float
    previous_high_20d: float
    breakout_pct: float
    relative_volume: float
    current_volume: float
    average_volume_20d: float
    rsi_14: float
    sma_50: float
    sma_200: float
    atr_14: float
    momentum_20d: float
    avg_dollar_volume_20d: float
    score: float
    score_components: dict[str, float]
    explanation: OpportunityExplanation
    configuration_hash: str
    data_provider: str
    session_status: Literal["COMPLETE"] = "COMPLETE"
    executed_at: datetime


class ScanSummary(BaseModel):
    symbols_requested: int
    symbols_processed: int
    symbols_skipped: int
    symbols_failed: int
    opportunities_found: int
    execution_duration: float
    exclusions: dict[str, str]


class ScanResponse(BaseModel):
    status: Literal["COMPLETED", "UNIVERSE_DATA_UNAVAILABLE"]
    as_of_date: date
    opportunities: list[OpportunityResult]
    summary: ScanSummary
