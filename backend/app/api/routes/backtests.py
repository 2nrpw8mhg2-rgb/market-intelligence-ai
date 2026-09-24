import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories import (
    BacktestRepository, MarketBarRepository, UniverseRepository,
)
from app.database.session import get_session
from app.schemas.backtesting import BacktestRequest
from app.services.backtesting import BacktestService

router = APIRouter(prefix="/api/v1/backtests", tags=["backtests"])


def service(session: AsyncSession) -> BacktestService:
    return BacktestService(
        bars=MarketBarRepository(session), universes=UniverseRepository(session),
        runs=BacktestRepository(session),
    )


@router.post("")
async def create_backtest(
    request: BacktestRequest, dry_run: bool = False,
    session: AsyncSession = Depends(get_session),
) -> dict:
    result = await service(session).execute(request, dry_run=dry_run)
    return result.model_dump(mode="json") if hasattr(result, "model_dump") else result


@router.get("")
async def list_backtests(
    limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    return await BacktestRepository(session).list(limit, offset)


async def _get(run_id: uuid.UUID, session: AsyncSession) -> dict:
    result = await BacktestRepository(session).get(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Backtest run not found")
    return result


@router.get("/{run_id}")
async def get_backtest(run_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> dict:
    return await _get(run_id, session)


@router.get("/{run_id}/summary")
async def get_backtest_summary(run_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> dict:
    result = await _get(run_id, session)
    return {key: value for key, value in result.items() if key != "events"}


@router.get("/{run_id}/events")
async def get_backtest_events(run_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> list[dict]:
    return (await _get(run_id, session)).get("events", [])
