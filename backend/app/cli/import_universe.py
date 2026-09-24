import argparse
import asyncio
import csv
from datetime import date
from pathlib import Path

from app.database.repositories import UniverseRepository
from app.database.session import SessionFactory
from app.schemas.universe import CurrentSnapshotImport


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Import a current universe snapshot from CSV")
    command.add_argument("--csv", required=True)
    command.add_argument("--snapshot-date", required=True, type=date.fromisoformat)
    command.add_argument("--source", required=True)
    command.add_argument("--ticker-column", default="ticker")
    return command


async def run(args: argparse.Namespace) -> None:
    with Path(args.csv).open(newline="", encoding="utf-8-sig") as handle:
        rows = csv.DictReader(handle)
        if not rows.fieldnames or args.ticker_column not in rows.fieldnames:
            raise ValueError(f"CSV must contain column {args.ticker_column!r}")
        tickers = [row[args.ticker_column] for row in rows]
    payload = CurrentSnapshotImport(
        tickers=tickers, snapshot_date=args.snapshot_date, source=args.source
    )
    async with SessionFactory() as session:
        imported = await UniverseRepository(session).import_current_snapshot("SP500", payload)
    print(f"Imported {imported} SP500 constituents for {payload.snapshot_date} from {payload.source}")


if __name__ == "__main__":
    asyncio.run(run(parser().parse_args()))
