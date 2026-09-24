from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.backtesting import FIXED_UNIVERSE_WARNING


RESEARCH_HORIZONS = (5, 10, 20, 60)
SCORE_BUCKETS = (0, 20, 40, 60, 80, 100)


class DependencyMode(StrEnum):
    ALL_EVENTS = "ALL_EVENTS"
    FIRST_SIGNAL_ONLY_20D = "FIRST_SIGNAL_ONLY_20D"
    FIRST_SIGNAL_ONLY_60D = "FIRST_SIGNAL_ONLY_60D"


class ScoreResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    backtest_run_id: str
    horizons: tuple[int, ...] = RESEARCH_HORIZONS
    score_buckets: tuple[float, ...] = SCORE_BUCKETS


class MarketRegimeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    backtest_run_id: str
    benchmark: str = "SPY"
    volatility_window: int = Field(default=20, ge=2)
    volatility_min_history: int = Field(default=60, ge=20)


class ResearchResult(BaseModel):
    run_id: str
    config_hash: str
    research_type: str
    source_backtest_run_id: str
    strategy_version: str
    universe_mode: str
    start_date: date
    end_date: date
    warning: str = FIXED_UNIVERSE_WARNING
    event_count: int
    results: dict[str, Any]
    created_at: datetime


class SelectionPolicy(StrEnum):
    HIGHEST_SCORE_FIRST = "HIGHEST_SCORE_FIRST"
    DETERMINISTIC_UNRANKED_BASELINE = "DETERMINISTIC_UNRANKED_BASELINE"


class PortfolioSimulationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    backtest_run_id: str
    initial_capital: float = Field(default=100_000, gt=0)
    maximum_positions: int = Field(default=10, ge=1)
    target_allocation: float = Field(default=0.10, gt=0, le=1)
    maximum_exposure: float = Field(default=1.0, gt=0, le=1)
    holding_period: int = Field(default=20, ge=1)
    commission_bps: float = Field(default=0, ge=0)
    slippage_bps: float = Field(default=5, ge=0)
    selection_policy: SelectionPolicy = SelectionPolicy.HIGHEST_SCORE_FIRST
    benchmark: str = "SPY"

    @model_validator(mode="after")
    def capacity_is_valid(self) -> "PortfolioSimulationRequest":
        if self.target_allocation * self.maximum_positions > self.maximum_exposure + 1e-12:
            raise ValueError("target allocation times maximum positions exceeds maximum exposure")
        return self


class PortfolioTradeResult(BaseModel):
    ticker: str
    signal_date: date
    entry_date: date
    exit_date: date
    score: float
    quantity: float
    reference_entry_price: float
    entry_price: float
    reference_exit_price: float
    exit_price: float
    gross_return: float
    net_return: float
    pnl: float
    commission: float
    slippage_cost: float
    holding_sessions: int
    exit_reason: str = "TIME_EXIT"


class PortfolioDailyResult(BaseModel):
    session_date: date
    cash: float
    positions_market_value: float
    gross_exposure: float
    net_exposure: float
    total_equity: float
    daily_return: float
    cumulative_return: float
    open_positions: int
    benchmark_equity: float | None


class SkippedSignalResult(BaseModel):
    ticker: str
    signal_date: date
    entry_date: date | None
    score: float
    reason: str


class PortfolioSimulationResult(BaseModel):
    run_id: str
    config_hash: str
    source_backtest_run_id: str
    warning: str = FIXED_UNIVERSE_WARNING
    strategy_version: str
    universe_mode: str
    start_date: date
    end_date: date
    configuration: dict[str, Any]
    metrics: dict[str, Any]
    benchmark_metrics: dict[str, Any]
    trades: list[PortfolioTradeResult]
    daily_equity: list[PortfolioDailyResult]
    skipped_signals: list[SkippedSignalResult]
    created_at: datetime
