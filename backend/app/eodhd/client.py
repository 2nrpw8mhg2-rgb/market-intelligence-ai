import asyncio
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import TypeAdapter, ValidationError

from app.core.logging import get_logger
from app.eodhd.models import CorporateAction, EODBar, HistoricalConstituent, SymbolChange

logger = get_logger(__name__)


class EODHDError(Exception):
    pass


class EODHDAuthenticationError(EODHDError):
    pass


class EODHDRateLimitError(EODHDError):
    pass


class EODHDResponseError(EODHDError):
    pass


@dataclass
class EODHDMetrics:
    network_requests: int = 0
    cache_hits: int = 0
    rate_limit_events: int = 0


class EODHDClient:
    """Minimal POC client. Tokens are query-only and never logged or cached."""

    def __init__(self, *, api_key: str, base_url: str = "https://eodhd.com/api",
                 timeout_seconds: float = 20, max_retries: int = 3,
                 retry_base_seconds: float = .5, cache_dir: Path | None = None,
                 client: httpx.AsyncClient | None = None, sleep=asyncio.sleep) -> None:
        if not api_key:
            raise ValueError("EODHD_API_KEY is required")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._retry_base = retry_base_seconds
        self._cache_dir = cache_dir
        self._client = client
        self._sleep = sleep
        self.metrics = EODHDMetrics()

    async def historical_constituents(self) -> list[HistoricalConstituent]:
        payload = await self._get("v1.1/fundamentals/GSPC.INDX", {"filter": "HistoricalTickerComponents"})
        values = list(payload.values()) if isinstance(payload, dict) else payload
        return self._validate_list(HistoricalConstituent, values, "historical constituents")

    async def historical_snapshot(self, as_of: date) -> Any:
        return await self._get("v1.1/fundamentals/GSPC.INDX", {
            "historical": 1, "from": as_of.isoformat(), "to": as_of.isoformat(),
            "filter": "HistoricalComponents",
        })

    async def eod(self, symbol: str, start: date | None = None, end: date | None = None) -> list[EODBar]:
        params: dict[str, Any] = {"period": "d", "order": "a"}
        if start:
            params["from"] = start.isoformat()
        if end:
            params["to"] = end.isoformat()
        payload = await self._get(f"eod/{quote(symbol.upper(), safe='.-')}", params)
        return self._validate_list(EODBar, payload, f"EOD {symbol}")

    async def symbol_changes(self, start: date, end: date) -> list[SymbolChange]:
        payload = await self._get("symbol-change-history", {
            "from": start.isoformat(), "to": end.isoformat(), "ex": "US",
        })
        return self._validate_list(SymbolChange, payload, "symbol changes")

    async def splits(self, symbol: str, start: date, end: date) -> list[CorporateAction]:
        payload = await self._get(f"splits/{quote(symbol.upper(), safe='.-')}", {
            "from": start.isoformat(), "to": end.isoformat(),
        })
        return self._validate_list(CorporateAction, payload, f"splits {symbol}")

    async def dividends(self, symbol: str, start: date, end: date) -> list[CorporateAction]:
        payload = await self._get(f"div/{quote(symbol.upper(), safe='.-')}", {
            "from": start.isoformat(), "to": end.isoformat(),
        })
        return self._validate_list(CorporateAction, payload, f"dividends {symbol}")

    async def fundamentals(self, symbol: str) -> dict[str, Any]:
        payload = await self._get(f"v1.1/fundamentals/{quote(symbol.upper(), safe='.-')}", {})
        if not isinstance(payload, dict):
            raise EODHDResponseError(f"fundamentals {symbol} must be an object")
        return payload

    async def fundamentals_general(self, symbol: str) -> dict[str, Any]:
        payload = await self._get(
            f"v1.1/fundamentals/{quote(symbol.upper(), safe='.-')}", {"filter": "General"}
        )
        if not isinstance(payload, dict):
            raise EODHDResponseError(f"fundamentals General {symbol} must be an object")
        return payload

    async def delisted_symbols(self) -> list[dict[str, Any]]:
        payload = await self._get("exchange-symbol-list/US", {"delisted": 1, "type": "common_stock"})
        if not isinstance(payload, list):
            raise EODHDResponseError("delisted symbol response must be a list")
        return payload

    async def _get(self, path: str, params: dict[str, Any]) -> Any:
        safe_params = {**params, "fmt": "json"}
        cache_key = self._cache_key(path, safe_params)
        if self._cache_dir:
            cache_file = self._cache_dir / f"{cache_key}.json"
            if cache_file.exists():
                self.metrics.cache_hits += 1
                return json.loads(cache_file.read_text())
        else:
            cache_file = None
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            payload = await self._request(client, f"{self._base_url}/{path.lstrip('/')}", {
                **safe_params, "api_token": self._api_key,
            })
        finally:
            if owns_client:
                await client.aclose()
        if cache_file:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(payload, separators=(",", ":")))
        return payload

    async def _request(self, client: httpx.AsyncClient, url: str, params: dict[str, Any]) -> Any:
        for attempt in range(self._max_retries + 1):
            try:
                self.metrics.network_requests += 1
                response = await client.get(url, params=params, timeout=self._timeout)
            except httpx.TransportError as exc:
                if attempt == self._max_retries:
                    raise EODHDError("EODHD transport failed after retries") from exc
                await self._sleep(self._retry_base * 2**attempt)
                continue
            if response.status_code in {401, 403}:
                raise EODHDAuthenticationError(f"EODHD authentication/access failed (http_status={response.status_code})")
            if response.status_code == 429:
                self.metrics.rate_limit_events += 1
                if attempt == self._max_retries:
                    raise EODHDRateLimitError("EODHD rate limit persisted after retries")
                await self._sleep(float(response.headers.get("Retry-After", self._retry_base * 2**attempt)))
                continue
            if response.status_code >= 500 and attempt < self._max_retries:
                await self._sleep(self._retry_base * 2**attempt)
                continue
            if response.status_code >= 400:
                raise EODHDResponseError(
                    f"EODHD request failed (http_status={response.status_code}, message={self._message(response)})"
                )
            try:
                return response.json()
            except ValueError as exc:
                raise EODHDResponseError(f"EODHD returned non-JSON data (http_status={response.status_code})") from exc
        raise EODHDError("EODHD request failed")

    @staticmethod
    def _validate_list(model, payload: Any, context: str):
        if not isinstance(payload, list):
            raise EODHDResponseError(f"{context} must be a list")
        try:
            return TypeAdapter(list[model]).validate_python(payload)
        except ValidationError as exc:
            field = ".".join(map(str, exc.errors(include_url=False, include_input=False)[0]["loc"]))
            raise EODHDResponseError(f"{context} validation failed (field={field})") from exc

    @staticmethod
    def _cache_key(path: str, params: dict[str, Any]) -> str:
        import hashlib
        canonical = json.dumps({"path": path, "params": params}, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    def _message(self, response: httpx.Response) -> str:
        value = " ".join((response.text or "no response message").split())
        return value.replace(self._api_key, "[REDACTED]")[:200]
