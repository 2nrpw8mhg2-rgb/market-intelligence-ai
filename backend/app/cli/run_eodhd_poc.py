import argparse
import asyncio
from datetime import date
from pathlib import Path
from typing import Any

from app.cli.common import emit_report
from app.core.config import get_settings
from app.database.repositories import MarketBarRepository
from app.database.session import SessionFactory
from app.eodhd import EODHDClient, build_membership_snapshot, parse_split_factor
from app.eodhd.audit import compare_provider_bars, coverage_diagnostics, duplicate_memberships, snapshot_diagnostics


SNAPSHOT_DATES = [date(2013, 6, 28), date(2016, 6, 30), date(2020, 6, 30), date(2022, 6, 30), date(2026, 6, 30)]
SAMPLE_SYMBOLS = ("AAPL", "NVDA", "META", "FB", "AAL", "ATVI", "LEH", "SIVB", "TWTR", "MON", "CELG", "GE")


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Run a bounded EODHD point-in-time data-quality POC")
    command.add_argument("--output", default="data/eodhd_poc/audit.json")
    command.add_argument("--cache-dir", default="data/eodhd_poc/cache")
    return command


async def safe(call, errors: list[dict], context: str):
    try:
        return await call
    except Exception as exc:
        errors.append({"context": context, "error_type": type(exc).__name__, "message": str(exc)[:300]})
        return None


async def run(args: argparse.Namespace) -> None:
    settings = get_settings()
    client = EODHDClient(
        api_key=settings.eodhd_api_key.get_secret_value(), base_url=settings.eodhd_base_url,
        timeout_seconds=settings.eodhd_timeout_seconds, max_retries=settings.eodhd_max_retries,
        retry_base_seconds=settings.eodhd_retry_base_seconds, cache_dir=Path(args.cache_dir),
    )
    errors: list[dict] = []
    constituents = await client.historical_constituents()
    provider_snapshots = {}
    for snapshot_date in SNAPSHOT_DATES:
        payload = await safe(client.historical_snapshot(snapshot_date), errors, f"snapshot:{snapshot_date}")
        provider_snapshots[snapshot_date.isoformat()] = {
            "response_type": type(payload).__name__ if payload is not None else None,
            "top_level_count": len(payload) if hasattr(payload, "__len__") else None,
            "top_level_keys": list(payload)[:10] if isinstance(payload, dict) else None,
        }

    symbol_changes = await safe(client.symbol_changes(date(2012, 1, 1), date(2026, 9, 28)), errors, "symbol_changes") or []
    delisted = await safe(client.delisted_symbols(), errors, "delisted_symbols") or []
    record_by_code = {item.code: item for item in constituents}
    sample_records = [record_by_code[code] for code in SAMPLE_SYMBOLS if code in record_by_code]
    prices = {}
    for record in sample_records:
        start = max(record.start_date or date(2012, 1, 1), date(2012, 1, 1))
        end = min(record.end_date or date(2026, 9, 22), date(2026, 9, 22))
        prices[record.code] = await safe(client.eod(f"{record.code}.US", start, end), errors, f"eod:{record.code}") or []

    fundamentals = {}
    for code in ("AAPL", "FB", "META", "ATVI", "AAL", "LEH", "SIVB"):
        payload = await safe(client.fundamentals(f"{code}.US"), errors, f"fundamentals:{code}")
        if payload:
            general = payload.get("General", {})
            fundamentals[code] = {key: general.get(key) for key in (
                "Code", "Name", "Exchange", "CurrencyCode", "CUSIP", "ISIN", "CIK",
                "PrimaryTicker", "OpenFigi", "LEI", "IsDelisted", "UpdatedAt",
            )}

    actions = {}
    for code in ("AAPL", "NVDA", "META", "GE"):
        splits = await safe(client.splits(f"{code}.US", date(2012, 1, 1), date(2026, 9, 22)), errors, f"splits:{code}") or []
        dividends = await safe(client.dividends(f"{code}.US", date(2012, 1, 1), date(2026, 9, 22)), errors, f"dividends:{code}") or []
        actions[code] = {
            "splits": [{**item.model_dump(mode="json"), "factor": parse_split_factor(item.split)} for item in splits if item.split],
            "dividends_count": len(dividends),
            "dividend_examples": [item.model_dump(mode="json") for item in dividends[-3:]],
        }

    comparisons = {}
    async with SessionFactory() as session:
        massive = MarketBarRepository(session)
        for code in ("AAPL", "NVDA", "META"):
            if code not in prices:
                record = record_by_code.get(code)
                start = max(record.start_date or date(2021, 9, 27), date(2021, 9, 27)) if record else date(2021, 9, 27)
                prices[code] = await safe(client.eod(f"{code}.US", start, date(2026, 9, 22)), errors, f"eod:{code}") or []
            massive_bars = await massive.list_daily_bars(code, date(2021, 9, 27), date(2026, 9, 22), provider="massive")
            comparisons[code] = compare_provider_bars(prices[code], massive_bars)

    fb_meta = [item.model_dump(mode="json") for item in symbol_changes if item.old_symbol == "FB" or item.new_symbol == "META"]
    delisted_index = {str(item.get("Code", "")).upper(): item for item in delisted}
    former = {}
    for record in sample_records:
        bars = prices.get(record.code, [])
        former[record.code] = {
            "name": record.name, "membership_start": record.start_date, "membership_end": record.end_date,
            "is_delisted": record.is_delisted, "delisted_directory": delisted_index.get(record.code),
            "first_eod": bars[0].date if bars else None, "last_eod": bars[-1].date if bars else None,
            "last_close": bars[-1].close if bars else None,
            "terminal_value_status": "UNKNOWN_TERMINAL_VALUE" if record.is_delisted else "NOT_ASSESSED",
        }

    report: dict[str, Any] = {
        "poc_scope": "BOUNDED_AUDIT_NO_PIT_BACKTEST", "as_of": date(2026, 9, 28),
        "requests": {"network": client.metrics.network_requests, "cache_hits": client.metrics.cache_hits,
                     "rate_limits": client.metrics.rate_limit_events},
        "historical_membership": {
            "records": len(constituents), "duplicates": duplicate_memberships(constituents),
            "missing_start_date": sum(item.start_date is None for item in constituents),
            "delisted_records": sum(item.is_delisted for item in constituents),
            "derived_snapshots_end_date_inclusive_assumption": [snapshot_diagnostics(constituents, item) for item in SNAPSHOT_DATES],
            "provider_snapshot_responses": provider_snapshots,
        },
        "identity": {"fundamentals": fundamentals, "fb_meta_changes": fb_meta,
                     "symbol_change_records": len(symbol_changes)},
        "former_constituents": former,
        "corporate_actions": actions,
        "coverage": coverage_diagnostics(sample_records, prices, date(2012, 1, 1), date(2026, 9, 22)),
        "provider_comparison": comparisons,
        "errors": errors,
    }
    emit_report(report, args.output)


if __name__ == "__main__":
    asyncio.run(run(parser().parse_args()))
