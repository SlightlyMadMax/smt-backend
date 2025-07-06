from datetime import datetime, timezone
from typing import Optional, Sequence

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

    async def list_open(self) -> Sequence[Position]:
        return await self.repo.list_open()

    async def list_bought(self) -> Sequence[Position]:
        return await self.repo.list_bought()

    async def list_listed(self) -> Sequence[Position]:
        return await self.repo.list_listed()

    async def list_closed(self) -> Sequence[Position]:
        return await self.repo.list_closed()

    async def mark_as_listed(
        self,
        position_id: int,
        sell_order_id: str,
        sell_price: float,
    ) -> Position:
        """
        Transition a Position from OPEN to LISTED: record sell_order_id and sell_price.
        """
        update_data = PositionUpdate(
            sell_order_id=sell_order_id,
            sell_price=sell_price,
            status=PositionStatus.LISTED.value,
        )
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
