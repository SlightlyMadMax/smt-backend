from typing import Sequence

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from smt.db.models import PoolItem
from smt.schemas.pool import PoolItemCreate, PoolItemUpdate


class PoolRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_items(self) -> Sequence[PoolItem]:
        result = await self.session.execute(select(PoolItem))
        return result.scalars().all()

    async def get_by_market_hash_name(self, market_hash_name: str) -> PoolItem:
        stmt = select(PoolItem).where(PoolItem.market_hash_name == market_hash_name)
        result = await self.session.execute(stmt)
        item = result.scalar_one_or_none()
        if item is None:
            raise NoResultFound(f"No PoolItem with hash {market_hash_name}")
        return item

    async def add_item(self, item: PoolItemCreate) -> bool:
        result = await self.session.execute(select(PoolItem).where(PoolItem.market_hash_name == item.market_hash_name))

        if result.scalar() is None:
            self.session.add(PoolItem(**item.model_dump()))
            try:
                await self.session.commit()
                return True
            except IntegrityError:
                await self.session.rollback()
        return False

    async def add_items(self, items: list[PoolItemCreate]) -> int:
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
                return len(new_items)
            except IntegrityError:
                await self.session.rollback()
        return 0

    async def update(
        self,
        market_hash_name: str,
        payload: PoolItemUpdate,
    ) -> bool:
        values = payload.model_dump(exclude_none=True)
        if not values:
            return False

        stmt = update(PoolItem).where(PoolItem.market_hash_name == market_hash_name).values(**values)
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount() > 0
