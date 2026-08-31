from typing import List, Sequence

from sqlalchemy import delete, select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from smt.db.models import Item


class ItemRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, item_id: str) -> Item:
        stmt = select(Item).where(Item.id == item_id)
        result = await self.session.execute(stmt)
        item = result.scalar_one_or_none()
        if not item:
            raise NoResultFound(f"Item with id {item_id} not found")
        return item

    async def list_by_game(self, app_id: str, context_id: str) -> Sequence[Item]:
        q = select(Item).where(Item.app_id == app_id, Item.context_id == context_id)
        res = await self.session.execute(q)
        return res.scalars().all()

    async def sync_for_game(self, app_id: str, context_id: str, items: List[Item]) -> set[str]:
        """Bring the stored inventory for a game in line with `items`."""
        existing = {item.id: item for item in await self.list_by_game(app_id, context_id)}
        incoming_ids = {item.id for item in items}

        stale_ids = set(existing) - incoming_ids
        if stale_ids:
            await self.session.execute(delete(Item).where(Item.id.in_(stale_ids)))

        new_ids: set[str] = set()
        for item in items:
            stored = existing.get(item.id)
            if stored is None:
                self.session.add(item)
                new_ids.add(item.id)
            else:
                stored.name = item.name
                stored.market_hash_name = item.market_hash_name
                stored.tradable = item.tradable
                stored.marketable = item.marketable
                stored.icon_url = item.icon_url

        await self.session.commit()
        return new_ids
