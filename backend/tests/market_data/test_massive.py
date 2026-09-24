from datetime import date

import httpx
import pytest

from app.market_data.exceptions import (
    MarketDataAuthenticationError,
    MarketDataError,
    MarketDataResponseError,
)
from app.market_data.massive import MassiveMarketDataProvider


@pytest.mark.asyncio
async def test_get_daily_bars_maps_ohlcv_and_normalizes_ticker() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["apiKey"] == "secret"
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "results": [
                    {"o": 100.0, "h": 105.0, "l": 99.0, "c": 103.0, "v": 1234, "t": 1704067200000}
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = MassiveMarketDataProvider(api_key="secret", client=client)
        bars = await provider.get_daily_bars(" aapl ", date(2024, 1, 1), date(2024, 1, 2))

    assert len(bars) == 1
    assert bars[0].ticker == "AAPL"
    assert bars[0].open == 100.0
    assert bars[0].high == 105.0
    assert bars[0].low == 99.0
    assert bars[0].close == 103.0
    assert bars[0].volume == 1234
    assert bars[0].timestamp.isoformat() == "2024-01-01T00:00:00+00:00"


@pytest.mark.asyncio
async def test_fractional_adjusted_volume_is_preserved() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "OK", "results": [
            {"o": 100, "h": 105, "l": 99, "c": 103,
             "v": 37_308_155.220558, "t": 1704067200000}
        ]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        bars = await MassiveMarketDataProvider(
            api_key="secret", client=client
        ).get_daily_bars("AAPL", date(2024, 1, 1), date(2024, 1, 1))

    assert bars[0].volume == pytest.approx(37_308_155.220558)


@pytest.mark.asyncio
async def test_http_error_contains_sanitized_diagnostics() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid date range"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = MassiveMarketDataProvider(api_key="secret", client=client)
        with pytest.raises(MarketDataResponseError) as captured:
            await provider.get_daily_bars("AAPL", date(2024, 1, 1), date(2024, 1, 2))

    message = str(captured.value)
    assert "http_status=400" in message
    assert "invalid date range" in message
    assert "secret" not in message


@pytest.mark.asyncio
async def test_get_daily_bars_follows_pagination() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={
                    "status": "OK",
                    "results": [{"o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 10, "t": 1704067200000}],
                    "next_url": "https://api.massive.com/next-page",
                },
            )
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "results": [{"o": 2, "h": 3, "l": 1.5, "c": 2.5, "v": 20, "t": 1704153600000}],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = MassiveMarketDataProvider(api_key="secret", client=client)
        bars = await provider.get_daily_bars("MSFT", date(2024, 1, 1), date(2024, 1, 2))

    assert len(requests) == 2
    assert requests[1].url.params["apiKey"] == "secret"
    assert [bar.close for bar in bars] == [1.5, 2.5]


@pytest.mark.asyncio
async def test_rate_limit_is_retried_using_retry_after() -> None:
    calls = 0
    delays: list[float] = []

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0.01"})
        return httpx.Response(200, json={"status": "OK", "results": []})

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = MassiveMarketDataProvider(
            api_key="secret", client=client, max_retries=1, sleep=fake_sleep
        )
        bars = await provider.get_daily_bars("AAPL", date(2024, 1, 1), date(2024, 1, 2))

    assert bars == []
    assert calls == 2
    assert delays == [0.01]


@pytest.mark.asyncio
async def test_authentication_error_is_not_retried() -> None:
    calls = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = MassiveMarketDataProvider(api_key="bad", client=client)
        with pytest.raises(MarketDataAuthenticationError):
            await provider.get_daily_bars("AAPL", date(2024, 1, 1), date(2024, 1, 2))

    assert calls == 1


@pytest.mark.asyncio
async def test_invalid_payload_raises_typed_error() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = MassiveMarketDataProvider(api_key="secret", client=client)
        with pytest.raises(MarketDataResponseError):
            await provider.get_daily_bars("AAPL", date(2024, 1, 1), date(2024, 1, 2))


@pytest.mark.asyncio
async def test_rejects_inverted_date_range() -> None:
    provider = MassiveMarketDataProvider(api_key="secret")

    with pytest.raises(ValueError, match="start_date"):
        await provider.get_daily_bars("AAPL", date(2024, 1, 2), date(2024, 1, 1))


@pytest.mark.asyncio
async def test_server_error_retries_then_fails() -> None:
    calls = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    async def no_sleep(_: float) -> None:
        return None

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = MassiveMarketDataProvider(
            api_key="secret", client=client, max_retries=1, sleep=no_sleep
        )
        with pytest.raises(MarketDataError, match="server error"):
            await provider.get_daily_bars("AAPL", date(2024, 1, 1), date(2024, 1, 2))

    assert calls == 2


@pytest.mark.asyncio
async def test_remote_protocol_error_is_retried() -> None:
    calls = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.RemoteProtocolError("server disconnected")
        return httpx.Response(200, json={"status": "OK", "results": []})

    async def no_sleep(_: float) -> None:
        return None

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = MassiveMarketDataProvider(
            api_key="secret", client=client, max_retries=1, sleep=no_sleep
        )
        assert await provider.get_daily_bars(
            "EXC", date(2024, 1, 1), date(2024, 1, 2)
        ) == []
    assert calls == 2


@pytest.mark.asyncio
async def test_unsuccessful_provider_status_is_rejected() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ERROR", "results": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = MassiveMarketDataProvider(api_key="secret", client=client)
        with pytest.raises(MarketDataResponseError, match="unsuccessful status"):
            await provider.get_daily_bars("AAPL", date(2024, 1, 1), date(2024, 1, 2))
