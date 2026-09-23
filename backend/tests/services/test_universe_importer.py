from datetime import date

import pytest
from pydantic import ValidationError

from app.schemas.universe import MembershipImportRecord
from app.services.universe import MembershipContradictionError, UniverseImporter


def record(start, end=None, ticker="AAPL", source="official-file"):
    return MembershipImportRecord(
        ticker=ticker, valid_from=start, valid_to=end, source=source
    )


class Store:
    def __init__(self):
        self.records = []

    async def list_membership_records(self, universe_name, tickers):
        return [value for value in self.records if value.ticker in tickers]

    async def upsert_memberships(self, universe_name, records):
        for incoming in records:
            identity = (incoming.ticker, incoming.valid_from, incoming.source)
            self.records = [
                current
                for current in self.records
                if (current.ticker, current.valid_from, current.source) != identity
            ]
            self.records.append(incoming)
        return len(records)


@pytest.mark.asyncio
async def test_import_is_idempotent() -> None:
    store = Store()
    importer = UniverseImporter(store)
    membership = record(date(2020, 1, 1))

    await importer.import_sp500([membership])
    await importer.import_sp500([membership])

    assert store.records == [membership]


def test_invalid_ticker_and_interval_are_rejected() -> None:
    with pytest.raises(ValidationError, match="ticker"):
        record(date(2020, 1, 1), ticker="bad ticker")
    with pytest.raises(ValidationError, match="valid_to"):
        record(date(2020, 2, 1), date(2020, 1, 1))


@pytest.mark.asyncio
async def test_overlapping_batch_memberships_are_rejected() -> None:
    importer = UniverseImporter(Store())
    with pytest.raises(MembershipContradictionError, match="overlapping"):
        await importer.import_sp500(
            [
                record(date(2020, 1, 1), date(2020, 12, 31)),
                record(date(2020, 6, 1), None, source="second-source"),
            ]
        )


@pytest.mark.asyncio
async def test_overlap_with_existing_membership_is_rejected() -> None:
    store = Store()
    store.records = [record(date(2020, 1, 1), date(2020, 12, 31))]

    with pytest.raises(MembershipContradictionError, match="overlapping"):
        await UniverseImporter(store).import_sp500(
            [record(date(2020, 6, 1), None, source="second-source")]
        )
