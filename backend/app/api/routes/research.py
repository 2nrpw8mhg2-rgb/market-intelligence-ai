import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories import BacktestRepository, MarketBarRepository, PortfolioRepository, ResearchRepository
from app.database.session import get_session
from app.schemas.research import MarketRegimeRequest, PortfolioSimulationRequest, ScoreResearchRequest
from app.services.research import ResearchService

router = APIRouter(prefix="/api/v1/research", tags=["research"])


def service(session: AsyncSession) -> ResearchService:
    return ResearchService(bars=MarketBarRepository(session), backtests=BacktestRepository(session),
                           research=ResearchRepository(session), portfolios=PortfolioRepository(session))


@router.post("/scores")
async def score(request: ScoreResearchRequest, dry_run: bool = False, session: AsyncSession = Depends(get_session)) -> dict:
    result = await service(session).score(request, dry_run=dry_run)
    return result.model_dump(mode="json") if hasattr(result, "model_dump") else result


@router.post("/regimes")
async def regimes(request: MarketRegimeRequest, dry_run: bool = False, session: AsyncSession = Depends(get_session)) -> dict:
    result = await service(session).regimes(request, dry_run=dry_run)
    return result.model_dump(mode="json") if hasattr(result, "model_dump") else result


@router.get("/runs")
async def list_runs(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), session: AsyncSession = Depends(get_session)) -> list[dict]:
    return await ResearchRepository(session).list(limit, offset)


@router.get("/runs/{run_id}")
async def get_run(run_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> dict:
    result = await ResearchRepository(session).get(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Research run not found")
    return result


@router.post("/portfolios")
async def portfolio(request: PortfolioSimulationRequest, dry_run: bool = False, session: AsyncSession = Depends(get_session)) -> dict:
    result = await service(session).portfolio(request, dry_run=dry_run)
    return result.model_dump(mode="json") if hasattr(result, "model_dump") else result


@router.get("/portfolios")
async def list_portfolios(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), session: AsyncSession = Depends(get_session)) -> list[dict]:
    return await PortfolioRepository(session).list(limit, offset)


@router.get("/portfolios/{run_id}")
async def get_portfolio(run_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> dict:
    result = await PortfolioRepository(session).get(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Portfolio simulation not found")
    return result


@router.get("/portfolios/{run_id}/{section}")
async def get_portfolio_section(run_id: uuid.UUID, section: str, session: AsyncSession = Depends(get_session)):
    allowed = {"trades", "daily_equity", "skipped_signals", "metrics", "benchmark_metrics"}
    if section not in allowed:
        raise HTTPException(status_code=404, detail="Portfolio section not found")
    result = await PortfolioRepository(session).get(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Portfolio simulation not found")
    return result[section]
