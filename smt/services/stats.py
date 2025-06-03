from datetime import datetime
from typing import List

from smt.repositories.stats import StatRepo
from smt.schemas.stats import ItemStatCreate


class StatService:
    def __init__(
        self,
        stat_repo: StatRepo,
    ):
        self.stat_repo = stat_repo

    async def list(self, market_hash_name: str, since: datetime):
        return await self.stat_repo.list_stats(market_hash_name, since)

    async def add_one(self, stat: ItemStatCreate):
        await self.stat_repo.add_stat(stat)

    async def add_many(self, stats: List[ItemStatCreate]):
        await self.stat_repo.add_stats(stats)
