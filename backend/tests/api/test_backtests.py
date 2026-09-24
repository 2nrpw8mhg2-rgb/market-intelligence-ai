import uuid

from fastapi.testclient import TestClient

from app.api.routes import backtests as routes
from app.main import create_app


RUN_ID = uuid.UUID("8c7f1bf6-e0b0-54da-a4bd-8e14b53f4ccb")


async def fake_session():
    yield object()


class FakeService:
    async def execute(self, request, *, dry_run=False):
        return {"status": "DRY_RUN" if dry_run else "COMPLETED", "events": []}


class FakeRepository:
    def __init__(self, session): pass
    async def list(self, limit=100, offset=0): return [{"run_id": str(RUN_ID)}]
    async def get(self, run_id):
        return {"run_id": str(run_id), "event_count": 0, "events": []} if run_id == RUN_ID else None


def app(monkeypatch):
    monkeypatch.setattr(routes, "service", lambda _session: FakeService())
    monkeypatch.setattr(routes, "BacktestRepository", FakeRepository)
    instance = create_app()
    instance.dependency_overrides[routes.get_session] = fake_session
    return instance


def payload():
    return {
        "universe_mode": "FIXED_UNIVERSE_RESEARCH",
        "tickers": ["AAPL"],
        "start_date": "2025-01-01",
        "end_date": "2025-12-31",
    }


def test_create_and_dry_run(monkeypatch) -> None:
    with TestClient(app(monkeypatch)) as client:
        assert client.post("/api/v1/backtests", json=payload()).json()["status"] == "COMPLETED"
        assert client.post("/api/v1/backtests?dry_run=true", json=payload()).json()["status"] == "DRY_RUN"


def test_list_detail_summary_events_and_not_found(monkeypatch) -> None:
    with TestClient(app(monkeypatch)) as client:
        assert client.get("/api/v1/backtests").status_code == 200
        assert client.get(f"/api/v1/backtests/{RUN_ID}").status_code == 200
        assert "events" not in client.get(f"/api/v1/backtests/{RUN_ID}/summary").json()
        assert client.get(f"/api/v1/backtests/{RUN_ID}/events").json() == []
        missing = client.get(f"/api/v1/backtests/{uuid.uuid4()}")
        assert missing.status_code == 404


def test_invalid_backtest_request_is_rejected(monkeypatch) -> None:
    invalid = payload()
    invalid["end_date"] = "2024-01-01"
    with TestClient(app(monkeypatch)) as client:
        assert client.post("/api/v1/backtests", json=invalid).status_code == 422
