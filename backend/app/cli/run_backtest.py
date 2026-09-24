import argparse
import asyncio
from datetime import date

from app.cli.common import emit_report, parse_tickers
from app.database.repositories import (
    BacktestRepository, MarketBarRepository, UniverseRepository,
)
from app.database.session import SessionFactory
from app.schemas.backtesting import BacktestRequest, EntryModel, UniverseMode
from app.services.backtesting import BacktestService


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Run a deterministic event-study backtest on stored bars")
    command.add_argument("--strategy", choices=["BREAKOUT_20D_VOLUME"], default="BREAKOUT_20D_VOLUME")
    command.add_argument("--universe-mode", choices=[item.value for item in UniverseMode], required=True)
    command.add_argument("--universe", default="SP500")
    command.add_argument("--tickers")
    command.add_argument("--start-date", type=date.fromisoformat, required=True)
    command.add_argument("--end-date", type=date.fromisoformat, required=True)
    command.add_argument("--entry-model", choices=[item.value for item in EntryModel], default="NEXT_OPEN")
    command.add_argument("--benchmark", default="SPY")
    command.add_argument("--dry-run", action="store_true")
    command.add_argument("--output")
    return command


async def run(args: argparse.Namespace) -> None:
    request = BacktestRequest(
        strategy=args.strategy, universe_mode=UniverseMode(args.universe_mode),
        universe_identifier=args.universe, tickers=parse_tickers(args.tickers) or None,
        start_date=args.start_date, end_date=args.end_date,
        entry_model=EntryModel(args.entry_model), benchmark=args.benchmark.upper(),
    )
    async with SessionFactory() as session:
        result = await BacktestService(
            bars=MarketBarRepository(session), universes=UniverseRepository(session),
            runs=BacktestRepository(session),
        ).execute(request, dry_run=args.dry_run)
    emit_report(result.model_dump(mode="json") if hasattr(result, "model_dump") else result, args.output)


if __name__ == "__main__":
    asyncio.run(run(parser().parse_args()))
