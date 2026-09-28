from pathlib import Path

import httpx
import pytest

from app.massive_audit.client import MassiveAuditClient, MassiveAuditError


@pytest.mark.asyncio
async def test_ticker_details_and_events_are_parsed_without_exposing_key(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["apiKey"] == "secret"
        if request.url.path.endswith("/events"):
            return httpx.Response(200, json={"status": "OK", "results": {"name": "Meta", "events": []}})
        return httpx.Response(200, json={"status": "OK", "results": {"ticker": "META", "cik": "1"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = MassiveAuditClient(api_key="secret", client=http, cache_dir=tmp_path, requests_per_minute=0)
        assert (await client.ticker_details("META", "2022-06-09"))["cik"] == "1"
        assert (await client.ticker_events("BBG000MM2P62"))["name"] == "Meta"


@pytest.mark.asyncio
async def test_cache_avoids_second_network_request(tmp_path: Path) -> None:
    calls = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"status": "OK", "results": {"ticker": "AAPL"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = MassiveAuditClient(api_key="secret", client=http, cache_dir=tmp_path, requests_per_minute=0)
        await client.ticker_details("AAPL", "2024-01-01")
        await client.ticker_details("AAPL", "2024-01-01")
    assert calls == 1
    assert client.metrics.cache_hits == 1


@pytest.mark.asyncio
async def test_aggregates_empty_results_are_not_filled(tmp_path: Path) -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json={"status": "OK", "results": []})
    )) as http:
        client = MassiveAuditClient(api_key="secret", client=http, cache_dir=tmp_path, requests_per_minute=0)
        assert await client.aggregates("OLD", "2020-01-01", "2020-01-31") == []


@pytest.mark.asyncio
async def test_error_redacts_api_key() -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda _: httpx.Response(400, text="bad secret")
    )) as http:
        client = MassiveAuditClient(api_key="secret", client=http, requests_per_minute=0)
        with pytest.raises(MassiveAuditError) as captured:
            await client.ticker_details("BAD", "2020-01-01")
    assert "secret" not in str(captured.value)
