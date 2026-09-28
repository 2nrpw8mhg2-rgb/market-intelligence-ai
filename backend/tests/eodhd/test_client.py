from datetime import date

import httpx
import pytest

from app.eodhd.audit import coverage_diagnostics, duplicate_memberships, snapshot_diagnostics
from app.eodhd.client import EODHDClient, EODHDAuthenticationError, EODHDResponseError
from app.eodhd.models import CorporateAction, HistoricalConstituent, SymbolChange, build_membership_snapshot, parse_split_factor


def constituent(code="ABC", start="2020-01-02", end=None, delisted=0):
    return HistoricalConstituent.model_validate({
        "Code": code, "Name": f"{code} Inc", "StartDate": start, "EndDate": end,
        "IsActiveNow": int(end is None), "IsDelisted": delisted,
    })


@pytest.mark.asyncio
async def test_historical_constituents_parsing_and_token_not_in_error() -> None:
    def handler(request: httpx.Request):
        assert request.url.params["api_token"] == "top-secret"
        return httpx.Response(200, json={"0": {
            "Code": " abc ", "Name": "ABC Inc", "StartDate": "2020-01-02",
            "EndDate": None, "IsActiveNow": 1, "IsDelisted": 0,
        }})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = EODHDClient(api_key="top-secret", client=http)
        result = await client.historical_constituents()
    assert result[0].code == "ABC"
    assert client.metrics.network_requests == 1


@pytest.mark.asyncio
async def test_eod_response_parsing_and_inclusive_dates() -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=[{
        "date": "2024-01-02", "open": 10, "high": 12, "low": 9, "close": 11,
        "adjusted_close": 10.5, "volume": 100,
    }]))) as http:
        result = await EODHDClient(api_key="x", client=http).eod("ABC.US", date(2024, 1, 2), date(2024, 1, 2))
    assert result[0].date == date(2024, 1, 2)
    assert result[0].adjusted_close == 10.5


@pytest.mark.asyncio
async def test_authentication_error_is_sanitized() -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(401, text="bad top-secret"))) as http:
        with pytest.raises(EODHDAuthenticationError) as error:
            await EODHDClient(api_key="top-secret", client=http).historical_constituents()
    assert "top-secret" not in str(error.value)


@pytest.mark.asyncio
async def test_provider_error_cannot_echo_token() -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda _: httpx.Response(400, text="invalid api_token top-secret")
    )) as http:
        with pytest.raises(EODHDResponseError) as error:
            await EODHDClient(api_key="top-secret", client=http).historical_constituents()
    assert "top-secret" not in str(error.value)
    assert "[REDACTED]" in str(error.value)


@pytest.mark.asyncio
async def test_invalid_payload_reports_context() -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"unexpected": True}))) as http:
        with pytest.raises(EODHDResponseError, match="EOD ABC.US must be a list"):
            await EODHDClient(api_key="x", client=http).eod("ABC.US", date(2024, 1, 1), date(2024, 1, 2))


def test_membership_interval_boundary_is_explicit() -> None:
    item = constituent(end="2020-01-10")
    assert item.is_member_on(date(2020, 1, 10), end_date_inclusive=True)
    assert not item.is_member_on(date(2020, 1, 10), end_date_inclusive=False)
    assert build_membership_snapshot([item], date(2020, 1, 10)) == [item]


def test_duplicate_membership_diagnostics_do_not_silently_deduplicate() -> None:
    records = [constituent("ABC", end="2020-03-01"), constituent("ABC", start="2021-01-01")]
    assert duplicate_memberships(records) == [{"code": "ABC", "records": 2}]
    assert snapshot_diagnostics(records, date(2020, 2, 1))["constituents"] == 1


def test_symbol_change_parsing_preserves_effective_date() -> None:
    change = SymbolChange.model_validate({"exchange": "US", "old_symbol": "fb", "new_symbol": "meta",
        "company_name": "Meta Platforms", "effective": "2022-06-09"})
    assert (change.old_symbol, change.new_symbol, change.effective) == ("FB", "META", date(2022, 6, 9))


@pytest.mark.parametrize(("ratio", "factor"), [("4.000000/1.000000", 4), ("1.000000/8.000000", .125), ("3/2", 1.5)])
def test_corporate_action_split_parsing(ratio: str, factor: float) -> None:
    assert CorporateAction(date=date(2020, 1, 1), split=ratio).split == ratio
    assert parse_split_factor(ratio) == factor


def test_missing_price_coverage_is_reported_not_filled() -> None:
    item = constituent(start="2024-01-02", end="2024-01-05")
    result = coverage_diagnostics([item], {"ABC": []}, date(2024, 1, 2), date(2024, 1, 5))
    assert result["membership_security_days"] == 4
    assert result["security_days_missing"] == 4
    assert result["coverage_pct"] == 0
