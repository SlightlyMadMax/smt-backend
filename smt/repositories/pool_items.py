from typing import Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from smt.db.models import PoolItem
from smt.schemas.pool import PoolItemCreate


class PoolRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_items(self) -> Sequence[PoolItem]:
        result = await self.session.execute(select(PoolItem))
        return result.scalars().all()

    async def add_item(self, item: PoolItemCreate) -> None:
        result = await self.session.execute(select(PoolItem).where(PoolItem.market_hash_name == item.market_hash_name))
        if result.scalar() is None:
            self.session.add(PoolItem(**item.model_dump()))
            try:
                await self.session.commit()
            except IntegrityError:
                await self.session.rollback()

    async def add_items(self, items: list[PoolItemCreate]) -> None:
        names = [item.market_hash_name for item in items]

        result = await self.session.execute(
            select(PoolItem.market_hash_name).where(PoolItem.market_hash_name.in_(names))
        )
        existing = {row[0] for row in result.all()}

        new_items = [PoolItem(**item.model_dump()) for item in items if item.market_hash_name not in existing]

        if new_items:
            self.session.add_all(new_items)
            try:
                await self.session.commit()
            except IntegrityError:
                await self.session.rollback()
