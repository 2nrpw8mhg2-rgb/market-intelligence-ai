import argparse
import asyncio
import sys
import time
from datetime import UTC, date, datetime

from app.cli.common import emit_report, parse_tickers
from app.core.config import get_settings
from app.database.repositories import MarketBarRepository, UniverseRepository
from app.database.session import SessionFactory
from app.market_data.calendar import NYSETradingCalendar, group_consecutive_sessions
from app.market_data.massive import MassiveMarketDataProvider
from app.services.market_data import MarketDataService


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Incrementally ingest Massive daily bars")
    command.add_argument("--universe", choices=["SP500"], default="SP500")
    command.add_argument("--provider", choices=["massive"], default="massive")
    command.add_argument("--tickers", help="Comma-separated symbols; defaults to current SP500 snapshot")
    command.add_argument("--end-date", type=date.fromisoformat)
    period = command.add_mutually_exclusive_group()
    period.add_argument("--start-date", type=date.fromisoformat)
    period.add_argument("--lookback-sessions", type=int)
    period.add_argument("--lookback-years", type=int)
    command.add_argument("--limit", type=int)
    command.add_argument("--concurrency", type=int)
    command.add_argument("--requests-per-minute", type=int, default=5,
                         help="Shared provider request budget (default: 5)")
    command.add_argument(
        "--dry-run",
        action="store_true",
        help="Estimate missing ranges, requests and minimum provider time without making calls",
    )
    command.add_argument("--output")
    return command


async def run(args: argparse.Namespace) -> None:
    started = time.perf_counter()
    settings = get_settings()
    calendar = NYSETradingCalendar()
    end = args.end_date or calendar.latest_complete_session(
        datetime.now(UTC),
        settings.provider_data_delay_minutes,
    )
    if args.start_date:
        start = args.start_date
    elif args.lookback_years:
        try:
            candidate = end.replace(year=end.year - args.lookback_years)
        except ValueError:
            candidate = end.replace(year=end.year - args.lookback_years, day=28)
        start = calendar.trading_days_between(candidate, end)[0]
    else:
        start = calendar.sessions_ending_on(end, args.lookback_sessions or 260)[0]
    tickers = parse_tickers(args.tickers)
    if not tickers:
        async with SessionFactory() as session:
            tickers = await UniverseRepository(session).list_current_members("SP500")
    if args.limit:
        tickers = tickers[: args.limit]
    if not tickers:
        raise RuntimeError("No tickers selected; import a current universe snapshot first")

    if args.dry_run:
        expected = calendar.trading_days_between(start, end)
        estimates: list[dict] = []
        async with SessionFactory() as session:
            repository = MarketBarRepository(session)
            for ticker in tickers:
                stored = await repository.list_daily_bars(ticker, start, end, provider=args.provider)
                available = {bar.timestamp.date() for bar in stored}
                missing = tuple(day for day in expected if day not in available)
                ranges = group_consecutive_sessions(missing, expected)
                estimates.append({
                    "ticker": ticker,
                    "stored_sessions": len(available),
                    "missing_sessions": len(missing),
                    "missing_intervals": [
                        {"start_date": interval_start, "end_date": interval_end}
                        for interval_start, interval_end in ranges
                    ],
                    "estimated_requests": len(ranges),
                })
        request_count = sum(item["estimated_requests"] for item in estimates)
        emit_report({
            "dry_run": True,
            "universe": args.universe,
            "provider": args.provider,
            "start_date": start,
            "end_date": end,
            "symbols_requested": len(tickers),
            "expected_sessions_per_symbol": len(expected),
            "missing_sessions": sum(item["missing_sessions"] for item in estimates),
            "estimated_provider_requests": request_count,
            "estimated_minimum_minutes": round(request_count / args.requests_per_minute, 2),
            "requests_per_minute": args.requests_per_minute,
            "results": estimates,
        }, args.output)
        return

    api_key = settings.massive_api_key.get_secret_value()
    if not api_key:
        raise RuntimeError("MASSIVE_API_KEY is not configured; no synthetic data will be used")
    provider = MassiveMarketDataProvider(
        api_key=api_key, base_url=settings.massive_base_url,
        timeout_seconds=settings.massive_timeout_seconds,
        max_retries=settings.massive_max_retries,
        retry_base_seconds=settings.massive_retry_base_seconds,
        requests_per_minute=args.requests_per_minute,
    )
    semaphore = asyncio.Semaphore(args.concurrency or settings.ingestion_concurrency)
    results: list[dict] = []

    async def ingest(ticker: str) -> None:
        async with semaphore, SessionFactory() as session:
            repository = MarketBarRepository(session)
            before = await repository.list_daily_bars(ticker, start, end, provider="massive")
            try:
                bars = await MarketDataService(provider, repository, calendar).get_or_ingest_daily_bars(ticker, start, end)
                complete = MarketDataService(provider, repository, calendar).assess_daily_completeness(bars, start, end).is_complete
                results.append({"ticker": ticker, "status": "complete" if complete else "partial", "available": len(bars),
                                "inserted": max(0, len(bars) - len(before))})
            except Exception as exc:
                results.append({"ticker": ticker, "status": "failed",
                                "error_type": type(exc).__name__, "error": str(exc)})
            print(f"[{len(results)}/{len(tickers)}] {ticker}: {results[-1]['status']}", file=sys.stderr)

    await asyncio.gather(*(ingest(ticker) for ticker in tickers))
    report = {"universe": args.universe, "provider": args.provider,
              "start_date": start, "end_date": end,
              "symbols_requested": len(tickers),
              "symbols_completed": sum(r["status"] == "complete" for r in results),
              "symbols_partial": sum(r["status"] == "partial" for r in results),
              "symbols_failed": sum(r["status"] == "failed" for r in results),
              "provider_requests": provider.metrics.requests,
              "bars_downloaded": provider.metrics.bars_received,
              "bars_inserted": sum(r.get("inserted", 0) for r in results),
              "bars_updated": 0,
              "rate_limit_events": provider.metrics.rate_limit_events,
              "execution_duration": round(time.perf_counter() - started, 3),
              "results": sorted(results, key=lambda row: row["ticker"])}
    emit_report(report, args.output)


if __name__ == "__main__":
    asyncio.run(run(parser().parse_args()))
