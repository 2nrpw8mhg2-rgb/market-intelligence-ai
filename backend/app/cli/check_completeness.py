import argparse
import asyncio
from datetime import date

from app.cli.common import emit_report, parse_tickers
from app.database.repositories import MarketBarRepository, UniverseRepository
from app.database.session import SessionFactory
from app.market_data.calendar import NYSETradingCalendar
from app.services.market_data import MarketDataService


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Report daily-bar completeness against XNYS sessions")
    command.add_argument("--start-date", required=True, type=date.fromisoformat)
    command.add_argument("--end-date", required=True, type=date.fromisoformat)
    command.add_argument("--tickers")
    command.add_argument("--limit", type=int)
    command.add_argument("--output")
    return command


async def run(args: argparse.Namespace) -> None:
    calendar = NYSETradingCalendar()
    async with SessionFactory() as session:
        repository = MarketBarRepository(session)
        tickers = parse_tickers(args.tickers) or await UniverseRepository(session).list_current_members("SP500")
        if args.limit:
            tickers = tickers[: args.limit]
        service = MarketDataService(provider=None, store=repository, calendar=calendar)  # type: ignore[arg-type]
        rows = []
        for ticker in tickers:
            bars = await repository.list_daily_bars(ticker, args.start_date, args.end_date, provider="massive")
            completeness = service.assess_daily_completeness(bars, args.start_date, args.end_date)
            diagnostics = await repository.daily_bar_diagnostics(
                ticker, args.start_date, args.end_date, provider="massive"
            )
            if not bars:
                status = "MISSING_DATA"
            elif len(bars) < 200:
                status = "INSUFFICIENT_HISTORY"
            elif completeness.is_complete:
                status = "COMPLETE"
            else:
                status = "PARTIAL"
            rows.append({"ticker": ticker, "status": status,
                         "first_session": diagnostics["first_session"],
                         "last_session": diagnostics["last_session"],
                         "last_updated": diagnostics["last_updated"],
                         "expected": len(completeness.expected_sessions),
                         "available": len(completeness.available_sessions),
                         "missing_count": len(completeness.missing_sessions),
                         "sufficient_for_sma200": len(bars) >= 200,
                         "missing_sessions": completeness.missing_sessions,
                         "unexpected_sessions": completeness.unexpected_sessions})
    emit_report({"start_date": args.start_date, "end_date": args.end_date,
                 "symbols": len(rows), "complete_symbols": sum(r["status"] == "COMPLETE" for r in rows),
                 "results": rows}, args.output)


if __name__ == "__main__":
    asyncio.run(run(parser().parse_args()))
