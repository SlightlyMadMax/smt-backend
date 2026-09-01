from datetime import datetime
from typing import List, Optional, Sequence

from sqlalchemy import delete, func, nulls_last, select
from sqlalchemy.ext.asyncio import AsyncSession

from smt.db.models import ActionLog
from smt.schemas.action_log import ActionLogSortKey
from smt.schemas.position import SortOrder


SORT_COLUMNS = {
    ActionLogSortKey.OCCURRED_AT: ActionLog.occurred_at,
    ActionLogSortKey.KIND: ActionLog.kind,
    ActionLogSortKey.LEVEL: ActionLog.level,
    ActionLogSortKey.MARKET_HASH_NAME: ActionLog.market_hash_name,
}


class ActionLogRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(
        self,
        kind: str,
        message: str,
        level: str = "info",
        market_hash_name: Optional[str] = None,
        position_id: Optional[int] = None,
    ) -> ActionLog:
        entry = ActionLog(
            kind=kind,
            message=message[:512],
            level=level,
            market_hash_name=market_hash_name,
            position_id=position_id,
        )
        self.session.add(entry)
        await self.session.commit()
        await self.session.refresh(entry)
        return entry

    async def list(
        self,
        limit: int = 200,
        level: Optional[str] = None,
        market_hash_name: Optional[str] = None,
    ) -> Sequence[ActionLog]:
        stmt = select(ActionLog).order_by(ActionLog.occurred_at.desc(), ActionLog.id.desc()).limit(limit)
        if level:
            stmt = stmt.where(ActionLog.level == level)
        if market_hash_name:
            stmt = stmt.where(ActionLog.market_hash_name == market_hash_name)

        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_page(
        self,
        limit: int,
        offset: int,
        level: Optional[str] = None,
        market_hash_name: Optional[str] = None,
        sort: ActionLogSortKey = ActionLogSortKey.OCCURRED_AT,
        order: SortOrder = SortOrder.DESC,
    ) -> Sequence[ActionLog]:
        column = SORT_COLUMNS[sort]
        direction = column.asc() if order is SortOrder.ASC else column.desc()

        stmt = select(ActionLog).order_by(nulls_last(direction), ActionLog.id.desc()).limit(limit).offset(offset)
        result = await self.session.execute(self._filtered(stmt, level, market_hash_name))
        return result.scalars().all()

    async def count(self, level: Optional[str] = None, market_hash_name: Optional[str] = None) -> int:
        stmt = self._filtered(select(func.count()).select_from(ActionLog), level, market_hash_name)
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    @staticmethod
    def _filtered(stmt, level: Optional[str], market_hash_name: Optional[str]):
        if level:
            stmt = stmt.where(ActionLog.level == level)
        if market_hash_name:
            stmt = stmt.where(ActionLog.market_hash_name == market_hash_name)
        return stmt

    async def list_kinds(self) -> List[str]:
        result = await self.session.execute(select(ActionLog.kind).distinct().order_by(ActionLog.kind))
        return [kind for kind, in result.all()]

    async def delete_before(self, before: datetime) -> int:
        result = await self.session.execute(delete(ActionLog).where(ActionLog.occurred_at < before))
        await self.session.commit()
        return result.rowcount
