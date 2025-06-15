from datetime import datetime
from typing import List, Sequence

from smt.db.models import PriceHistoryRecord
from smt.db.models import PriceHistoryRecord as PriceHistoryRecordORM
from smt.repositories.price_history import PriceHistoryRepo
from smt.schemas.price_history import PriceHistoryRecordCreate


class PriceHistoryService:
    def __init__(
        self,
        price_history_repo: PriceHistoryRepo,
    ):
        self.price_history_repo = price_history_repo

    async def list(self, market_hash_name: str, since: datetime) -> Sequence[PriceHistoryRecordORM]:
        return await self.price_history_repo.list_records(market_hash_name, since)

    async def add_one(self, price_record: PriceHistoryRecordCreate) -> PriceHistoryRecord:
        return await self.price_history_repo.add_record(price_record)

    async def add_many(self, price_records: List[PriceHistoryRecordCreate]) -> List[PriceHistoryRecord]:
        return await self.price_history_repo.add_records(price_records)

    async def delete_before(self, market_hash_name: str, before_date: datetime) -> int:
        return await self.price_history_repo.delete_records_before(market_hash_name, before_date)
