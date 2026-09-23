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
