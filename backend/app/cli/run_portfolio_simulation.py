import argparse
import asyncio

from app.cli.common import emit_report
from app.database.repositories import BacktestRepository, MarketBarRepository, PortfolioRepository, ResearchRepository
from app.database.session import SessionFactory
from app.schemas.research import PortfolioSimulationRequest, SelectionPolicy
from app.services.research import ResearchService


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Run deterministic long-only portfolio simulation")
    command.add_argument("--backtest-run-id", required=True)
    command.add_argument("--initial-capital", type=float, default=100_000)
    command.add_argument("--maximum-positions", type=int, default=10)
    command.add_argument("--target-allocation", type=float, default=.10)
    command.add_argument("--holding-period", type=int, default=20)
    command.add_argument("--commission-bps", type=float, default=0)
    command.add_argument("--slippage-bps", type=float, default=5)
    command.add_argument("--selection-policy", choices=[item.value for item in SelectionPolicy], default=SelectionPolicy.HIGHEST_SCORE_FIRST.value)
    command.add_argument("--benchmark", default="SPY")
    command.add_argument("--dry-run", action="store_true")
    command.add_argument("--output")
    return command


async def run(args: argparse.Namespace) -> None:
    request = PortfolioSimulationRequest(
        backtest_run_id=args.backtest_run_id, initial_capital=args.initial_capital,
        maximum_positions=args.maximum_positions, target_allocation=args.target_allocation,
        holding_period=args.holding_period, commission_bps=args.commission_bps,
        slippage_bps=args.slippage_bps, selection_policy=SelectionPolicy(args.selection_policy),
        benchmark=args.benchmark.upper(),
    )
    async with SessionFactory() as session:
        result = await ResearchService(
            bars=MarketBarRepository(session), backtests=BacktestRepository(session),
            research=ResearchRepository(session), portfolios=PortfolioRepository(session),
        ).portfolio(request, dry_run=args.dry_run)
    emit_report(result.model_dump(mode="json") if hasattr(result, "model_dump") else result, args.output)


if __name__ == "__main__":
    asyncio.run(run(parser().parse_args()))
