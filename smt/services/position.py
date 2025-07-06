from datetime import datetime, timezone
from typing import List, Optional, Sequence

from smt.db.models import Position, PositionStatus
from smt.repositories.position import PositionRepo
from smt.schemas.position import PositionCreate, PositionUpdate


class PositionService:
    def __init__(self, repo: PositionRepo):
        self.repo = repo

    async def add(
        self,
        data: PositionCreate,
    ) -> Position:
        """
        Create a new Position in OPEN state using PositionCreate schema.
        """
        pos = await self.repo.add(data)
        return pos

    async def list(self) -> Sequence[Position]:
        return await self.repo.list_positions()

    async def list_by_status(self, status: PositionStatus) -> Sequence[Position]:
        return await self.repo.list_by_status(status=status)

    async def list_active(self) -> List[Position]:
        open_ = await self.list_by_status(status=PositionStatus.OPEN)
        bought = await self.list_by_status(status=PositionStatus.BOUGHT)
        listed = await self.list_by_status(status=PositionStatus.LISTED)

        return list(open_) + list(bought) + list(listed)

    async def mark_as_bought(self, position_id: int, asset_id: str) -> Position:
        """
        Transition a Position from OPEN to BOUGHT.
        """
        pos = await self.get(position_id)
        if pos.status != PositionStatus.OPEN:
            raise ValueError("Can only mark OPEN positions as BOUGHT")
        update_data = PositionUpdate(asset_id=asset_id, status=PositionStatus.BOUGHT.value)
        pos = await self.repo.update(position_id, update_data)
        return pos

    async def mark_as_listed(self, position_id: int, sell_order_id: str) -> Position:
        """
        Transition a Position from BOUGHT to LISTED.
        """
        pos = await self.get(position_id)
        if pos.status != PositionStatus.BOUGHT:
            raise ValueError("Can only mark BOUGHT positions as LISTED")
        update_data = PositionUpdate(sell_order_id=sell_order_id, status=PositionStatus.LISTED.value)
        pos = await self.repo.update(position_id, update_data)
        return pos

    async def close(
        self,
        position_id: int,
        sold_at: Optional[datetime] = None,
    ) -> Position:
        """
        Transition a LISTED Position to CLOSED: record sold_at timestamp.
        """
        pos = await self.get(position_id)
        if pos.status != PositionStatus.LISTED:
            raise ValueError("Can only close positions that are LISTED")
        sold_at = sold_at or datetime.now(timezone.utc)
        update_data = PositionUpdate(
            status=PositionStatus.CLOSED.value,
            sold_at=sold_at,
        )
        pos = await self.repo.update(position_id, update_data)
        return pos

    async def get(self, position_id: int) -> Position:
        pos = await self.repo.get_by_id(position_id)
        return pos

    async def delete(self, position_id: int) -> None:
        await self.repo.delete(position_id)
