from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.api.routes import features as feature_routes
from app.main import create_app
from app.schemas.market_data import MarketBar


class FakeRepository:
    def __init__(self, session) -> None:
        pass

    async def list_daily_bars(self, ticker, start_date=None, end_date=None, provider=None):
        return [
            MarketBar(
                ticker=ticker,
                timestamp=datetime(2024, 1, day, tzinfo=UTC),
                open=10 + day,
                high=12 + day,
                low=9 + day,
                close=11 + day,
                volume=100 + day,
            )
            for day in range(1, 3)
        ]


async def fake_session():
    yield object()


def test_feature_endpoint_returns_stored_bars_and_null_warmups(monkeypatch) -> None:
    monkeypatch.setattr(feature_routes, "MarketBarRepository", FakeRepository)
    app = create_app()
    app.dependency_overrides[feature_routes.get_session] = fake_session

    with TestClient(app) as client:
        response = client.get("/api/v1/features/aapl")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ticker"] == "AAPL"
    assert payload["count"] == 2
    assert payload["rows"][0]["SMA_20"] is None
    assert payload["rows"][1]["RETURN_1D"] == pytest.approx(13 / 12 - 1)


def test_feature_endpoint_rejects_inverted_dates() -> None:
    app = create_app()
    app.dependency_overrides[feature_routes.get_session] = fake_session

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/features/AAPL?start_date=2024-02-01&end_date=2024-01-01"
        )

    assert response.status_code == 422
