from datetime import date

import pytest

from app.market_data.universe import SP500Universe, UniverseName


class FakeUniverseRepository:
    def __init__(self) -> None:
        self.arguments = None

    async def list_members(self, name, as_of):
        self.arguments = (name, as_of)
        return ["AAPL", "MSFT"]


@pytest.mark.asyncio
async def test_sp500_universe_is_resolved_point_in_time() -> None:
    repository = FakeUniverseRepository()
    universe = SP500Universe(repository)

    members = await universe.members(date(2024, 1, 1))

    assert universe.name is UniverseName.SP500
    assert members == ["AAPL", "MSFT"]
    assert repository.arguments == ("SP500", date(2024, 1, 1))


@pytest.mark.asyncio
async def test_point_in_time_query_does_not_include_future_members() -> None:
    class PointInTimeRepository:
        async def list_members(self, name, as_of):
            memberships = [
                ("AAPL", date(2010, 1, 1), None),
                ("FUTURE", date(2025, 1, 1), None),
                ("REMOVED", date(2010, 1, 1), date(2020, 12, 31)),
            ]
            return [
                ticker
                for ticker, valid_from, valid_to in memberships
                if valid_from <= as_of and (valid_to is None or valid_to >= as_of)
            ]

    members = await SP500Universe(PointInTimeRepository()).members(date(2024, 6, 15))

    assert members == ["AAPL"]
