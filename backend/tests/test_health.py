from fastapi.testclient import TestClient

from app.main import create_app


def test_health_returns_service_metadata(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "test")

    with TestClient(create_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "market-intelligence-api",
        "version": "0.2.0",
        "environment": "test",
    }


def test_openapi_exposes_health() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/health" in response.json()["paths"]
