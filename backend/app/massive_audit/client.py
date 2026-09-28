import asyncio
import hashlib
import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin

import httpx


class MassiveAuditError(Exception):
    pass


@dataclass
class MassiveAuditMetrics:
    requests: int = 0
    cache_hits: int = 0
    rate_limits: int = 0


class MassiveAuditClient:
    """Read-only POC client for Massive reference/corporate-action evidence."""

    def __init__(self, *, api_key: str, base_url: str = "https://api.massive.com",
                 cache_dir: Path | None = None, requests_per_minute: int = 5,
                 timeout_seconds: float = 20, max_retries: int = 3,
                 retry_base_seconds: float = .5, client: httpx.AsyncClient | None = None,
                 sleep=asyncio.sleep) -> None:
        if not api_key:
            raise ValueError("MASSIVE_API_KEY is required")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/") + "/"
        self._cache_dir = cache_dir
        self._rpm = requests_per_minute
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._retry_base = retry_base_seconds
        self._client = client
        self._sleep = sleep
        self._times: deque[float] = deque()
        self._lock = asyncio.Lock()
        self.metrics = MassiveAuditMetrics()

    async def ticker_details(self, ticker: str, as_of: str) -> dict[str, Any]:
        payload = await self._get(f"v3/reference/tickers/{quote(ticker, safe='.-_')}", {"date": as_of})
        result = payload.get("results")
        return result if isinstance(result, dict) else {}

    async def ticker_events(self, identifier: str) -> dict[str, Any]:
        payload = await self._get(f"vX/reference/tickers/{quote(identifier, safe='.-_')}/events", {})
        result = payload.get("results")
        return result if isinstance(result, dict) else {}

    async def aggregates(self, ticker: str, start: str, end: str) -> list[dict[str, Any]]:
        path = f"v2/aggs/ticker/{quote(ticker, safe='.-_')}/range/1/day/{start}/{end}"
        payload = await self._get(path, {"adjusted": "true", "sort": "asc", "limit": 50000})
        results = payload.get("results")
        return results if isinstance(results, list) else []

    async def splits(self, ticker: str) -> list[dict[str, Any]]:
        payload = await self._get("stocks/v1/splits", {"ticker": ticker, "limit": 5000,
                                                        "sort": "execution_date.asc"})
        results = payload.get("results")
        return results if isinstance(results, list) else []

    async def dividends(self, ticker: str) -> list[dict[str, Any]]:
        payload = await self._get("stocks/v1/dividends", {"ticker": ticker, "limit": 5000,
                                                           "sort": "ex_dividend_date.asc"})
        results = payload.get("results")
        return results if isinstance(results, list) else []

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        safe_params = dict(params)
        key = hashlib.sha256(json.dumps({"path": path, "params": safe_params}, sort_keys=True,
                                        separators=(",", ":")).encode()).hexdigest()
        cache_file = self._cache_dir / f"{key}.json" if self._cache_dir else None
        if cache_file and cache_file.exists():
            self.metrics.cache_hits += 1
            return json.loads(cache_file.read_text())
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            payload = await self._request(client, urljoin(self._base_url, path), safe_params)
        finally:
            if owns_client:
                await client.aclose()
        if cache_file:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(payload, separators=(",", ":")))
        return payload

    async def _request(self, client: httpx.AsyncClient, url: str, params: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(self._max_retries + 1):
            await self._throttle()
            self.metrics.requests += 1
            try:
                response = await client.get(url, params={**params, "apiKey": self._api_key}, timeout=self._timeout)
            except httpx.TransportError as exc:
                if attempt == self._max_retries:
                    raise MassiveAuditError("Massive transport failed after retries") from exc
                await self._sleep(self._retry_base * 2**attempt)
                continue
            if response.status_code in {401, 403}:
                raise MassiveAuditError(f"Massive access failed (http_status={response.status_code})")
            if response.status_code == 429:
                self.metrics.rate_limits += 1
                if attempt == self._max_retries:
                    raise MassiveAuditError("Massive rate limit persisted after retries")
                await self._sleep(float(response.headers.get("Retry-After", self._retry_base * 2**attempt)))
                continue
            if response.status_code >= 500 and attempt < self._max_retries:
                await self._sleep(self._retry_base * 2**attempt)
                continue
            if response.status_code >= 400:
                raise MassiveAuditError(
                    f"Massive response failed (http_status={response.status_code}, message={self._message(response)})"
                )
            try:
                payload = response.json()
            except ValueError as exc:
                raise MassiveAuditError(f"Massive returned non-JSON (http_status={response.status_code})") from exc
            if not isinstance(payload, dict):
                raise MassiveAuditError("Massive response must be a JSON object")
            return payload
        raise MassiveAuditError("Massive request failed")

    async def _throttle(self) -> None:
        if not self._rpm:
            return
        async with self._lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            while self._times and now - self._times[0] >= 60:
                self._times.popleft()
            if len(self._times) >= self._rpm:
                await self._sleep(60 - (now - self._times[0]) + .05)
                now = loop.time()
                while self._times and now - self._times[0] >= 60:
                    self._times.popleft()
            self._times.append(now)

    def _message(self, response: httpx.Response) -> str:
        value = " ".join((response.text or "no response message").split())
        return value.replace(self._api_key, "[REDACTED]")[:240]
