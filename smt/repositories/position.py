from typing import Sequence

from sqlalchemy import delete, select, update
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from smt.db.models import Position
from smt.schemas.position import PositionCreate, PositionStatus, PositionUpdate


class PositionRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, position_id: int) -> Position:
        stmt = select(Position).where(Position.id == position_id)
        result = await self.session.execute(stmt)
        pos = result.scalar_one_or_none()
        if not pos:
            raise NoResultFound(f"Position with id {position_id} not found")
        return pos

    async def list_by_status(self, status: PositionStatus) -> Sequence[Position]:
        stmt = select(Position).where(Position.status == status)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_open(self) -> Sequence[Position]:
        return await self.list_by_status(PositionStatus.OPEN)

    async def list_bought(self) -> Sequence[Position]:
        return await self.list_by_status(PositionStatus.BOUGHT)

    async def list_listed(self) -> Sequence[Position]:
        return await self.list_by_status(PositionStatus.LISTED)

    async def list_closed(self) -> Sequence[Position]:
        return await self.list_by_status(PositionStatus.CLOSED)

    async def add(self, data: PositionCreate) -> Position:
        pos = Position(
            pool_item_hash=data.pool_item_hash,
            buy_order_id=data.buy_order_id,
            buy_price=data.buy_price,
            sell_price=data.sell_price,
            quantity=data.quantity,
            status=PositionStatus.OPEN,
        )
        self.session.add(pos)
        await self.session.commit()
        await self.session.refresh(pos)
        return pos

    async def update(self, position_id: int, data: PositionUpdate) -> Position:
        stmt = (
            update(Position)
            .where(Position.id == position_id)
            .values(
                sell_order_id=data.sell_order_id,
                status=data.status,
                sold_at=data.sold_at,
            )
            .execution_options(synchronize_session="fetch")
        )
        await self.session.execute(stmt)
        await self.session.commit()
        return await self.get_by_id(position_id)

    async def delete(self, position_id: int) -> None:
        stmt = delete(Position).where(Position.id == position_id)
        await self.session.execute(stmt)
        await self.session.commit()
