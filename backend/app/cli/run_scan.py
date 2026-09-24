import argparse
import asyncio
from datetime import date

from app.cli.common import emit_report
from app.core.config import get_settings
from app.database.repositories import MarketBarRepository, OpportunityRepository, UniverseRepository
from app.database.session import SessionFactory
from app.market_data.calendar import NYSETradingCalendar
from app.market_data.universe import SP500Universe
from app.schemas.scanner import ScanMode, ScanRequest
from app.services.scanner import ScannerService


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Run and persist the deterministic scanner")
    command.add_argument("--mode", choices=[mode.value for mode in ScanMode], default="LATEST")
    command.add_argument("--as-of-date", type=date.fromisoformat)
    command.add_argument("--output")
    return command


async def run(args: argparse.Namespace) -> None:
    settings = get_settings()
    request = ScanRequest(mode=ScanMode(args.mode), as_of_date=args.as_of_date)
    async with SessionFactory() as session:
        response = await ScannerService(
            universe=SP500Universe(UniverseRepository(session)),
            bars=MarketBarRepository(session),
            opportunities=OpportunityRepository(session),
            calendar=NYSETradingCalendar(),
            provider_delay_minutes=settings.provider_data_delay_minutes,
        ).scan(request)
    emit_report(response.model_dump(mode="json"), args.output)


if __name__ == "__main__":
    asyncio.run(run(parser().parse_args()))
