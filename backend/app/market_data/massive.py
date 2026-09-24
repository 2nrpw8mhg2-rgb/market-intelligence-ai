import asyncio
from collections import deque
from dataclasses import dataclass
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urljoin

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.logging import get_logger
from app.market_data.base import MarketDataProvider
from app.market_data.exceptions import (
    MarketDataAuthenticationError,
    MarketDataError,
    MarketDataRateLimitError,
    MarketDataResponseError,
)
from app.schemas.market_data import MarketBar

logger = get_logger(__name__)


@dataclass
class ProviderMetrics:
    requests: int = 0
    bars_received: int = 0
    rate_limit_events: int = 0


class _MassiveAggregate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    open: float = Field(alias="o")
    high: float = Field(alias="h")
    low: float = Field(alias="l")
    close: float = Field(alias="c")
    volume: float = Field(alias="v", ge=0)
    timestamp_ms: int = Field(alias="t")


class _MassivePage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str
    results: list[_MassiveAggregate] = Field(default_factory=list)
    next_url: str | None = None


class MassiveMarketDataProvider(MarketDataProvider):
    name = "massive"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.massive.com",
        timeout_seconds: float = 15.0,
        max_retries: int = 3,
        retry_base_seconds: float = 0.25,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        requests_per_minute: int | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("MASSIVE_API_KEY is required")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/") + "/"
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._retry_base_seconds = retry_base_seconds
        self._client = client
        self._sleep = sleep
        self._requests_per_minute = requests_per_minute
        self._request_times: deque[float] = deque()
        self._rate_lock = asyncio.Lock()
        self.metrics = ProviderMetrics()

    async def get_daily_bars(
        self, ticker: str, start_date: date, end_date: date
    ) -> list[MarketBar]:
        normalized_ticker = ticker.strip().upper()
        if not normalized_ticker:
            raise ValueError("ticker cannot be empty")
        if start_date > end_date:
            raise ValueError("start_date must be on or before end_date")

        path = (
            f"v2/aggs/ticker/{normalized_ticker}/range/1/day/"
            f"{start_date.isoformat()}/{end_date.isoformat()}"
        )
        next_url: str | None = urljoin(self._base_url, path)
        params: dict[str, Any] | None = {
            "adjusted": "true",
            "sort": "asc",
            "limit": 50000,
            "apiKey": self._api_key,
        }
        bars: list[MarketBar] = []

        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            while next_url:
                payload, http_status = await self._request_json(client, next_url, params=params)
                params = {"apiKey": self._api_key}
                try:
                    page = _MassivePage.model_validate(payload)
                except ValidationError as exc:
                    first = exc.errors(include_url=False, include_input=False)[0]
                    field = ".".join(str(part) for part in first["loc"])
                    raise MarketDataResponseError(
                        "Massive response validation failed "
                        f"(http_status={http_status}, ticker={normalized_ticker}, "
                        f"range={start_date}/{end_date}, field={field}, "
                        f"message={self._sanitize_message(first['msg'])})"
                    ) from exc
                if page.status not in {"OK", "DELAYED"}:
                    provider_message = self._payload_message(payload)
                    raise MarketDataResponseError(
                        "Massive returned unsuccessful status from provider "
                        f"(http_status={http_status}, provider_status={page.status}, "
                        f"ticker={normalized_ticker}, range={start_date}/{end_date}, "
                        f"message={provider_message})"
                    )
                bars.extend(self._to_bar(normalized_ticker, item) for item in page.results)
                self.metrics.bars_received += len(page.results)
                next_url = page.next_url
        finally:
            if owns_client:
                await client.aclose()

        bars.sort(key=lambda bar: bar.timestamp)
        logger.info(
            "market_data_fetched",
            extra={"provider": self.name, "ticker": normalized_ticker, "bar_count": len(bars)},
        )
        return bars

    async def _request_json(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        params: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], int]:
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                await self._throttle()
                self.metrics.requests += 1
                response = await client.get(url, params=params, timeout=self._timeout)
            except httpx.TransportError as exc:
                last_error = exc
                if attempt >= self._max_retries:
                    raise MarketDataError("Massive request failed after retries") from exc
                await self._sleep(self._retry_delay(attempt))
                continue

            if response.status_code in {401, 403}:
                raise MarketDataAuthenticationError(
                    "Massive authentication failed "
                    f"(http_status={response.status_code}, "
                    f"message={self._response_message(response)})"
                )
            if response.status_code == 429:
                self.metrics.rate_limit_events += 1
                if attempt >= self._max_retries:
                    raise MarketDataRateLimitError(
                        "Massive rate limit exceeded "
                        f"(http_status=429, message={self._response_message(response)})"
                    )
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else self._retry_delay(attempt)
                await self._sleep(delay)
                continue
            if response.status_code >= 500:
                last_error = httpx.HTTPStatusError(
                    "Massive server error", request=response.request, response=response
                )
                if attempt >= self._max_retries:
                    raise MarketDataError(
                        "Massive server error after retries "
                        f"(http_status={response.status_code}, "
                        f"message={self._response_message(response)})"
                    ) from last_error
                await self._sleep(self._retry_delay(attempt))
                continue
            try:
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPStatusError, ValueError) as exc:
                raise MarketDataResponseError(
                    "Massive returned an invalid HTTP response "
                    f"(http_status={response.status_code}, "
                    f"message={self._response_message(response)})"
                ) from exc
            if not isinstance(payload, dict):
                raise MarketDataResponseError(
                    "Massive response must be a JSON object "
                    f"(http_status={response.status_code})"
                )
            return payload, response.status_code

        raise MarketDataError("Massive request failed") from last_error

    def _retry_delay(self, attempt: int) -> float:
        return self._retry_base_seconds * (2**attempt)

    async def _throttle(self) -> None:
        if not self._requests_per_minute:
            return
        async with self._rate_lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            while self._request_times and now - self._request_times[0] >= 60:
                self._request_times.popleft()
            if len(self._request_times) >= self._requests_per_minute:
                delay = 60 - (now - self._request_times[0]) + 0.1
                await self._sleep(delay)
                now = loop.time()
                while self._request_times and now - self._request_times[0] >= 60:
                    self._request_times.popleft()
            self._request_times.append(now)

    @classmethod
    def _response_message(cls, response: httpx.Response) -> str:
        try:
            payload = response.json()
            if isinstance(payload, dict):
                value = payload.get("message") or payload.get("error") or payload.get("status")
                if value:
                    return cls._sanitize_message(str(value))
        except ValueError:
            pass
        return cls._sanitize_message(response.text or "no response message")

    @classmethod
    def _payload_message(cls, payload: dict[str, Any]) -> str:
        value = payload.get("message") or payload.get("error") or payload.get("status")
        return cls._sanitize_message(str(value or "no provider message"))

    @staticmethod
    def _sanitize_message(value: str) -> str:
        # Provider messages are diagnostic only; keep them single-line and bounded.
        return " ".join(value.split())[:300]

    @staticmethod
    def _to_bar(ticker: str, aggregate: _MassiveAggregate) -> MarketBar:
        return MarketBar(
            ticker=ticker,
            timestamp=datetime.fromtimestamp(aggregate.timestamp_ms / 1000, tz=UTC),
            open=aggregate.open,
            high=aggregate.high,
            low=aggregate.low,
            close=aggregate.close,
            volume=aggregate.volume,
        )
