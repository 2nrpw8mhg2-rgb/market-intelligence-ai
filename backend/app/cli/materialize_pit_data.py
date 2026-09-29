import argparse
import asyncio
import json
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path

from app.database.repositories import MarketBarRepository, UniverseRepository
from app.database.session import SessionFactory
from app.market_data.calendar import NYSETradingCalendar
from app.pit.materialization import (
    build_materialization_records, cached_eodhd_bars, database_validation, write_ledger,
)
from app.schemas.market_data import MarketBar
from app.services.universe import UniverseImporter


START = date(2021, 9, 27)
END = date(2026, 9, 22)
PRE_IDENTITY_CORRECTION_HASH = "51c3041e7a1f8d11218dfa056d4171e51cf88c4947b2714e01a9e9af4287b5fd"
EXPECTED_HASH = "74d14b5198a7e64e91127abbbdcaae087e8c9134f6e8f6786446c210e2529b4d"


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Materialize validated security-id-native PIT membership")
    command.add_argument("--audit", default="data/eodhd_poc3/audit.json")
    command.add_argument("--exceptions", default="docs/PIT_MEMBERSHIP_EXCEPTIONS.json")
    command.add_argument("--identity-evidence", default="docs/PIT_ALIAS_CHAIN_EVIDENCE.json")
    command.add_argument("--ledger", default="docs/PIT_HISTORICAL_ALIAS_LEDGER.csv")
    command.add_argument("--cache-dir", default="data/eodhd_poc/cache")
    command.add_argument("--import-missing-prices", action="store_true")
    command.add_argument("--import-all-eodhd-prices", action="store_true")
    command.add_argument("--tickers", nargs="*", help="Limit price materialization to these corrected tickers")
    return command


async def run(args: argparse.Namespace) -> None:
    audit = json.loads(Path(args.audit).read_text())
    exceptions = json.loads(Path(args.exceptions).read_text())
    identity_evidence = json.loads(Path(args.identity_evidence).read_text())
    records, ledger = build_materialization_records(
        audit, exceptions, START, END, identity_evidence
    )
    write_ledger(Path(args.ledger), ledger)
    imported_aliases = imported_bars = 0
    provider_counts: Counter[str] = Counter()
    async with SessionFactory() as session:
        repository = UniverseRepository(session)
        persisted = await UniverseImporter(repository).import_sp500(records)
        database_records = await repository.list_period_memberships("SP500", START, END)
        bars_repository = MarketBarRepository(session)
        if args.import_missing_prices or args.import_all_eodhd_prices:
            ledger_by_ticker = {item.historical_ticker: item for item in ledger}
            for record in database_records:
                if args.tickers and record.ticker not in set(args.tickers):
                    continue
                provider, existing = await bars_repository.list_security_daily_bars(
                    record.security_id, record.ticker, providers=("massive",)
                )
                if existing and not args.import_all_eodhd_prices:
                    provider_counts[provider or "unknown"] += 1
                    continue
                item = ledger_by_ticker[record.ticker]
                cached = cached_eodhd_bars(Path(args.cache_dir), item.provider_symbol)
                converted = []
                for bar in cached:
                    if bar.close <= 0 or bar.adjusted_close <= 0:
                        continue
                    factor = bar.adjusted_close / bar.close
                    adjusted_open = bar.open * factor
                    adjusted_close = bar.adjusted_close
                    # Provider rounding can put adjusted_close a few ulps outside
                    # scaled high/low. Preserve OHLC validity without inventing a
                    # price by widening only to the observed adjusted endpoints.
                    adjusted_high = max(bar.high * factor, adjusted_open, adjusted_close)
                    adjusted_low = min(bar.low * factor, adjusted_open, adjusted_close)
                    converted.append(MarketBar(
                        ticker=record.ticker,
                        timestamp=datetime.combine(bar.date, datetime.min.time(), tzinfo=UTC),
                        open=adjusted_open, high=adjusted_high,
                        low=adjusted_low, close=adjusted_close,
                        volume=bar.volume / factor,
                    ))
                imported_bars += await bars_repository.upsert_daily_bars(
                    converted, provider="eodhd_adjusted_derived"
                )
                imported_aliases += 1
                provider_counts["eodhd_adjusted_derived"] += 1
    sessions = NYSETradingCalendar().trading_days_between(START, END)
    validation = database_validation(database_records, sessions)
    if validation.deterministic_hash != EXPECTED_HASH:
        raise RuntimeError(
            f"database PIT hash mismatch: expected={EXPECTED_HASH}, actual={validation.deterministic_hash}"
        )
    print(json.dumps({
        "records_submitted": len(records), "records_persisted": persisted,
        "database_records": len(database_records), "sessions": len(sessions),
        "hash": validation.deterministic_hash,
        "pre_identity_correction_hash": PRE_IDENTITY_CORRECTION_HASH,
        "ledger": dict(Counter(item.resolution_status for item in ledger)),
        "price_alias_providers": dict(provider_counts),
        "price_aliases_imported": imported_aliases, "bars_imported": imported_bars,
        "blocking_anomalies": sum(item.get("blocking", True) for item in validation.anomalies),
    }, indent=2))


if __name__ == "__main__":
    asyncio.run(run(parser().parse_args()))
