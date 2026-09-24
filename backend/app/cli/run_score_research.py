import argparse
import asyncio

from app.cli.common import emit_report
from app.database.repositories import BacktestRepository, MarketBarRepository, PortfolioRepository, ResearchRepository
from app.database.session import SessionFactory
from app.schemas.research import ScoreResearchRequest
from app.services.research import ResearchService


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Research score buckets and component relationships")
    command.add_argument("--backtest-run-id", required=True)
    command.add_argument("--dry-run", action="store_true")
    command.add_argument("--output")
    return command


async def run(args: argparse.Namespace) -> None:
    async with SessionFactory() as session:
        result = await ResearchService(
            bars=MarketBarRepository(session), backtests=BacktestRepository(session),
            research=ResearchRepository(session), portfolios=PortfolioRepository(session),
        ).score(ScoreResearchRequest(backtest_run_id=args.backtest_run_id), dry_run=args.dry_run)
    emit_report(result.model_dump(mode="json") if hasattr(result, "model_dump") else result, args.output)


if __name__ == "__main__":
    asyncio.run(run(parser().parse_args()))
