import argparse
import asyncio

from app.cli.common import emit_report
from app.database.repositories import BacktestRepository, MarketBarRepository, PortfolioRepository, ResearchRepository
from app.database.session import SessionFactory
from app.schemas.research import MarketRegimeRequest
from app.services.research import ResearchService


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Classify causal SPY market regimes for a backtest")
    command.add_argument("--backtest-run-id", required=True)
    command.add_argument("--benchmark", default="SPY")
    command.add_argument("--dry-run", action="store_true")
    command.add_argument("--output")
    return command


async def run(args: argparse.Namespace) -> None:
    async with SessionFactory() as session:
        result = await ResearchService(
            bars=MarketBarRepository(session), backtests=BacktestRepository(session),
            research=ResearchRepository(session), portfolios=PortfolioRepository(session),
        ).regimes(MarketRegimeRequest(backtest_run_id=args.backtest_run_id, benchmark=args.benchmark.upper()), dry_run=args.dry_run)
    emit_report(result.model_dump(mode="json") if hasattr(result, "model_dump") else result, args.output)


if __name__ == "__main__":
    asyncio.run(run(parser().parse_args()))
