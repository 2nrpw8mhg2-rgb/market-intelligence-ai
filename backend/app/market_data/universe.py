from abc import ABC, abstractmethod
from datetime import date
from enum import StrEnum

from app.database.repositories import UniverseRepository


class UniverseName(StrEnum):
    SP500 = "SP500"
    NASDAQ100 = "NASDAQ100"
    RUSSELL2000 = "RUSSELL2000"
    CUSTOM = "CUSTOM"


class MarketUniverse(ABC):
    name: UniverseName

    @abstractmethod
    async def members(self, as_of: date) -> list[str]:
        raise NotImplementedError

    async def current_members(self) -> list[str]:
        raise NotImplementedError


class SP500Universe(MarketUniverse):
    name = UniverseName.SP500

    def __init__(self, repository: UniverseRepository) -> None:
        self._repository = repository

    async def members(self, as_of: date) -> list[str]:
        return await self._repository.list_members(self.name.value, as_of)

    async def current_members(self) -> list[str]:
        return await self._repository.list_current_members(self.name.value)
