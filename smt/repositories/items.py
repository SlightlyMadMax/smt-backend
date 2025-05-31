from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from smt.db.models import Item


class ItemRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_for_game(self, app_id: str, context_id: str):
        q = select(Item).where(Item.app_id == app_id, Item.context_id == context_id)
        res = await self.session.execute(q)
        return res.scalars().all()

    async def replace_for_game(self, items: list[Item]):
        if not items:
            return
        app_id = items[0].app_id
        context_id = items[0].context_id
        # delete old
        await self.session.execute(delete(Item).where(Item.app_id == app_id, Item.context_id == context_id))
        # bulk insert
        self.session.add_all(items)
        await self.session.commit()
