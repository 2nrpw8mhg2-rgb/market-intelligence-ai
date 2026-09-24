from datetime import date

from fastapi.testclient import TestClient

from app.api.routes import scanner as routes
from app.main import create_app
from app.schemas.scanner import ScanResponse, ScanSummary


async def fake_session():
    yield object()


class FakeScannerService:
    def __init__(self, **kwargs): pass
    async def scan(self, request):
        return ScanResponse(
            status="COMPLETED", as_of_date=request.as_of_date or date(2024, 1, 2),
            opportunities=[],
            summary=ScanSummary(
                symbols_requested=0, symbols_processed=0, symbols_skipped=0,
                symbols_failed=0, opportunities_found=0, execution_duration=0,
                exclusions={},
            ),
        )


class FakeOpportunityRepository:
    arguments = None
    def __init__(self, session): pass
    async def list(self, **kwargs):
        FakeOpportunityRepository.arguments = kwargs
        return []


def app(monkeypatch):
    monkeypatch.setattr(routes, "ScannerService", FakeScannerService)
    monkeypatch.setattr(routes, "OpportunityRepository", FakeOpportunityRepository)
    instance = create_app()
    instance.dependency_overrides[routes.get_session] = fake_session
    return instance


def test_post_scan(monkeypatch) -> None:
    with TestClient(app(monkeypatch)) as client:
        response = client.post("/api/v1/scan", json={
            "mode": "HISTORICAL", "as_of_date": "2024-01-02",
            "universe": "SP500", "strategy": "BREAKOUT_20D_VOLUME",
        })
    assert response.status_code == 200
    assert response.json()["status"] == "COMPLETED"


def test_historical_scan_requires_date(monkeypatch) -> None:
    with TestClient(app(monkeypatch)) as client:
        response = client.post("/api/v1/scan", json={"mode": "HISTORICAL"})
    assert response.status_code == 422


def test_opportunity_filters_and_pagination(monkeypatch) -> None:
    with TestClient(app(monkeypatch)) as client:
        response = client.get(
            "/api/v1/opportunities?date=2024-01-02&ticker=AAPL&min_score=70&limit=10&offset=5"
        )
    assert response.status_code == 200
    assert FakeOpportunityRepository.arguments["ticker"] == "AAPL"
    assert FakeOpportunityRepository.arguments["limit"] == 10
    assert FakeOpportunityRepository.arguments["offset"] == 5


def test_opportunity_history_and_invalid_pagination(monkeypatch) -> None:
    with TestClient(app(monkeypatch)) as client:
        assert client.get("/api/v1/opportunities/AAPL").status_code == 200
        assert client.get("/api/v1/opportunities?limit=0").status_code == 422
