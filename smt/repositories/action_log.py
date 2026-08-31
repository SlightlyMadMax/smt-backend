from datetime import datetime
from typing import List, Optional, Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from smt.db.models import ActionLog


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

    async def list_kinds(self) -> List[str]:
        result = await self.session.execute(select(ActionLog.kind).distinct().order_by(ActionLog.kind))
        return [kind for kind, in result.all()]

    async def delete_before(self, before: datetime) -> int:
        result = await self.session.execute(delete(ActionLog).where(ActionLog.occurred_at < before))
        await self.session.commit()
        return result.rowcount
