from collections import defaultdict
from datetime import date
from typing import Protocol

from app.market_data.universe import UniverseName
from app.schemas.universe import MembershipImportRecord


class MembershipContradictionError(ValueError):
    pass


class UniverseMembershipStore(Protocol):
    async def list_membership_records(
        self, universe_name: str, tickers: set[str]
    ) -> list[MembershipImportRecord]: ...

    async def upsert_memberships(
        self, universe_name: str, records: list[MembershipImportRecord]
    ) -> int: ...


class UniverseImporter:
    def __init__(self, store: UniverseMembershipStore) -> None:
        self._store = store

    async def import_sp500(self, records: list[MembershipImportRecord]) -> int:
        if not records:
            return 0
        records = list(dict.fromkeys(records))
        self._reject_batch_contradictions(records)
        existing = await self._store.list_membership_records(
            UniverseName.SP500.value, {record.ticker for record in records}
        )
        self._reject_existing_contradictions(records, existing)
        return await self._store.upsert_memberships(UniverseName.SP500.value, records)

    def _reject_batch_contradictions(self, records: list[MembershipImportRecord]) -> None:
        grouped: dict[str, list[MembershipImportRecord]] = defaultdict(list)
        for record in records:
            grouped[record.ticker].append(record)
        for ticker, ticker_records in grouped.items():
            self._validate_non_overlapping(ticker, ticker_records)

    def _reject_existing_contradictions(
        self,
        incoming: list[MembershipImportRecord],
        existing: list[MembershipImportRecord],
    ) -> None:
        for new in incoming:
            for current in existing:
                if new.ticker != current.ticker:
                    continue
                same_identity = (
                    new.valid_from == current.valid_from and new.source == current.source
                )
                if not same_identity and self._overlaps(new, current):
                    raise MembershipContradictionError(
                        f"overlapping membership intervals for {new.ticker}"
                    )

    @classmethod
    def _validate_non_overlapping(
        cls, ticker: str, records: list[MembershipImportRecord]
    ) -> None:
        ordered = sorted(records, key=lambda record: record.valid_from)
        for previous, current in zip(ordered, ordered[1:]):
            if cls._overlaps(previous, current):
                exact_duplicate = previous == current
                if not exact_duplicate:
                    raise MembershipContradictionError(
                        f"overlapping membership intervals for {ticker}"
                    )

    @staticmethod
    def _overlaps(left: MembershipImportRecord, right: MembershipImportRecord) -> bool:
        max_date = date.max
        return left.valid_from <= (right.valid_to or max_date) and right.valid_from <= (
            left.valid_to or max_date
        )
