from datetime import date

import pandas as pd
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories import MarketBarRepository
from app.database.session import get_session
from app.features import FeatureEngine
from app.schemas.features import FeatureSeriesResponse, serialize_feature_rows

router = APIRouter(prefix="/api/v1/features", tags=["features"])


@router.get("/{ticker}", response_model=FeatureSeriesResponse)
async def get_features(
    ticker: str,
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> FeatureSeriesResponse:
    if start_date and end_date and start_date > end_date:
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail="start_date must not exceed end_date")
    normalized_ticker = ticker.strip().upper()
    bars = await MarketBarRepository(session).list_daily_bars(
        normalized_ticker, start_date, end_date
    )
    frame = pd.DataFrame([bar.model_dump() for bar in bars])
    if frame.empty:
        frame = pd.DataFrame(
            columns=["ticker", "timestamp", "open", "high", "low", "close", "volume"]
        )
    features = FeatureEngine().calculate(frame)
    rows = serialize_feature_rows(features.to_dict(orient="records"))
    return FeatureSeriesResponse(
        ticker=normalized_ticker,
        start_date=start_date,
        end_date=end_date,
        count=len(rows),
        rows=rows,
    )
