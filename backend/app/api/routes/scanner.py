from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories import MarketBarRepository, OpportunityRepository, UniverseRepository
from app.database.session import get_session
from app.core.config import get_settings
from app.market_data.calendar import NYSETradingCalendar
from app.market_data.universe import SP500Universe
from app.schemas.scanner import OpportunityResult, ScanRequest, ScanResponse
from app.services.scanner import ScannerService

router = APIRouter(prefix="/api/v1", tags=["scanner"])


@router.post("/scan", response_model=ScanResponse)
async def scan(request: ScanRequest, session: AsyncSession = Depends(get_session)) -> ScanResponse:
    service = ScannerService(
        universe=SP500Universe(UniverseRepository(session)),
        bars=MarketBarRepository(session), opportunities=OpportunityRepository(session),
        calendar=NYSETradingCalendar(),
        provider_delay_minutes=get_settings().provider_data_delay_minutes,
    )
    return await service.scan(request)


@router.get("/opportunities", response_model=list[OpportunityResult])
async def opportunities(
    date_: date | None = Query(default=None, alias="date"), ticker: str | None = None,
    strategy: str | None = None, universe: str | None = None,
    min_score: float | None = Query(default=None, ge=0, le=100),
    limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    return await OpportunityRepository(session).list(
        scan_date=date_, ticker=ticker, strategy=strategy, universe=universe,
        min_score=min_score, limit=limit, offset=offset,
    )


@router.get("/opportunities/{ticker}", response_model=list[OpportunityResult])
async def opportunity_history(
    ticker: str, limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0), session: AsyncSession = Depends(get_session),
) -> list[dict]:
    return await OpportunityRepository(session).list(ticker=ticker, limit=limit, offset=offset)
