import uuid
from typing import Any

from app.database.repositories import (
    BacktestRepository, MarketBarStore, PortfolioRepository, ResearchRepository,
)
from app.portfolio import PortfolioEngine
from app.research import MarketRegimeEngine, ScoreResearchEngine
from app.schemas.backtesting import BacktestRunResult, EntryModel, UniverseMode
from app.schemas.research import (
    MarketRegimeRequest, PortfolioSimulationRequest, PortfolioSimulationResult,
    ResearchResult, ScoreResearchRequest,
)


class ResearchService:
    def __init__(self, *, bars: MarketBarStore, backtests: BacktestRepository,
                 research: ResearchRepository, portfolios: PortfolioRepository) -> None:
        self.bars = bars
        self.backtests = backtests
        self.research = research
        self.portfolios = portfolios

    async def _source(self, run_id: str) -> BacktestRunResult:
        document = await self.backtests.get(uuid.UUID(run_id))
        if document is None:
            raise ValueError(f"source backtest run not found: {run_id}")
        source = BacktestRunResult.model_validate(document)
        if source.universe_mode is not UniverseMode.FIXED_UNIVERSE_RESEARCH:
            raise ValueError("Phase 6 research requires a FIXED_UNIVERSE_RESEARCH source run")
        return source

    async def score(self, request: ScoreResearchRequest, *, dry_run: bool = False) -> ResearchResult | dict[str, Any]:
        source = await self._source(request.backtest_run_id)
        if dry_run:
            return {"status": "DRY_RUN", "source_backtest_run_id": source.run_id,
                    "event_count": source.event_count, "horizons": request.horizons,
                    "score_buckets": request.score_buckets}
        result = ScoreResearchEngine().run(request, source)
        await self.research.save(result, request.model_dump(mode="json"))
        return result

    async def regimes(self, request: MarketRegimeRequest, *, dry_run: bool = False) -> ResearchResult | dict[str, Any]:
        source = await self._source(request.backtest_run_id)
        benchmark = await self.bars.list_daily_bars(request.benchmark, source.start_date, source.end_date)
        if dry_run:
            return {"status": "DRY_RUN", "source_backtest_run_id": source.run_id,
                    "event_count": source.event_count, "benchmark": request.benchmark,
                    "benchmark_bars": len(benchmark)}
        result = MarketRegimeEngine().run(request, source, benchmark)
        await self.research.save(result, request.model_dump(mode="json"))
        return result

    async def portfolio(self, request: PortfolioSimulationRequest, *, dry_run: bool = False) -> PortfolioSimulationResult | dict[str, Any]:
        source = await self._source(request.backtest_run_id)
        if source.entry_model is not EntryModel.NEXT_OPEN:
            raise ValueError("portfolio simulation requires a NEXT_OPEN source backtest")
        tickers = sorted({event.ticker for event in source.events})
        if dry_run:
            return {"status": "DRY_RUN", "source_backtest_run_id": source.run_id,
                    "event_count": source.event_count, "symbols": len(tickers),
                    "configuration": request.model_dump(mode="json")}
        bars = {ticker: await self.bars.list_daily_bars(ticker, source.start_date, source.end_date)
                for ticker in tickers}
        benchmark = await self.bars.list_daily_bars(request.benchmark, source.start_date, source.end_date)
        result = PortfolioEngine().run(request, source, bars, benchmark)
        await self.portfolios.save(result)
        return result
