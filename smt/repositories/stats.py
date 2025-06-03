from datetime import datetime
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from smt.db.models import ItemStat as ItemStatORM
from smt.schemas.stats import ItemStatCreate


class StatRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_stats(self, market_hash_name: str, since: datetime) -> Sequence[ItemStatORM]:
        stmt = (
            select(ItemStatORM)
            .where(
                ItemStatORM.market_hash_name == market_hash_name,
                ItemStatORM.recorded_at >= since,
            )
            .order_by(ItemStatORM.recorded_at)
        )
        result = await self.session.execute(stmt)

        return result.scalars().all()

    async def add_stat(self, stat: ItemStatCreate) -> None:
        self.session.add(ItemStatORM(**stat.model_dump()))
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()

    async def add_stats(self, stats: list[ItemStatCreate]) -> None:
        values = [stat.model_dump() for stat in stats]

        stmt = insert(ItemStatORM).values(values)

        # On conflict, do nothing (skip duplicates)
        stmt = stmt.on_conflict_do_nothing(index_elements=["market_hash_name", "recorded_at"])

        try:
            await self.session.execute(stmt)
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
