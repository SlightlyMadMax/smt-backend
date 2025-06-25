from typing import Optional, Sequence

from sqlalchemy import delete, select, update
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

    async def get_many(self, market_hash_names: list[str]) -> Sequence[PoolItem]:
        if not market_hash_names:
            return []
        stmt = select(PoolItem).where(PoolItem.market_hash_name.in_(market_hash_names))
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def add_item(self, item: PoolItemCreate) -> Optional[PoolItem]:
        stmt = select(PoolItem).where(PoolItem.market_hash_name == item.market_hash_name)
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            return None

        # Create and add new item
        new_item = PoolItem(**item.model_dump())
        self.session.add(new_item)

        try:
            await self.session.commit()
            await self.session.refresh(new_item)
            return new_item
        except IntegrityError:
            await self.session.rollback()
            return None

    async def add_items(self, items: list[PoolItemCreate]) -> list[PoolItem]:
        names = [item.market_hash_name for item in items]

        # Find existing items
        result = await self.session.execute(
            select(PoolItem.market_hash_name).where(PoolItem.market_hash_name.in_(names))
        )
        existing = {name for name, in result.all()}

        new_items = [PoolItem(**item.model_dump()) for item in items if item.market_hash_name not in existing]

        if new_items:
            self.session.add_all(new_items)
            try:
                await self.session.commit()
                for item in new_items:
                    await self.session.refresh(item)
                return new_items
            except IntegrityError:
                await self.session.rollback()

        return []

    async def update(self, market_hash_name: str, payload: PoolItemUpdate) -> Optional[PoolItem]:
        update_data = payload.model_dump(exclude_unset=True)
        if not update_data:
            return None

        stmt = update(PoolItem).where(PoolItem.market_hash_name == market_hash_name).values(**update_data)
        await self.session.execute(stmt)
        await self.session.commit()

        try:
            return await self.get_by_market_hash_name(market_hash_name)
        except NoResultFound:
            return None

    async def remove(self, market_hash_name: str) -> bool:
        stmt = delete(PoolItem).where(PoolItem.market_hash_name == market_hash_name)
        result = await self.session.execute(stmt)
        await self.session.commit()

        return result.rowcount > 0

    async def remove_many(self, market_hash_names: list[str]) -> int:
        if not market_hash_names:
            return 0

        stmt = delete(PoolItem).where(PoolItem.market_hash_name.in_(market_hash_names))
        result = await self.session.execute(stmt)
        await self.session.commit()

        return result.rowcount
