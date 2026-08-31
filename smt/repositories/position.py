from datetime import datetime
from decimal import Decimal
from typing import Optional, Sequence

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from smt.db.models import Position
from smt.schemas.position import ACTIVE_STATUSES, PositionCreate, PositionStatus, PositionUpdate


class PositionRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, position_id: int) -> Position:
        stmt = select(Position).options(selectinload(Position.pool_item)).where(Position.id == position_id)
        result = await self.session.execute(stmt)
        pos = result.scalar_one_or_none()
        if not pos:
            raise NoResultFound(f"Position with id {position_id} not found")
        return pos

    async def list(self) -> Sequence[Position]:
        stmt = select(Position).options(selectinload(Position.pool_item))
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_by_status(self, status: PositionStatus) -> Sequence[Position]:
        stmt = select(Position).options(selectinload(Position.pool_item)).where(Position.status == status)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def realized_profit_since(self, since: datetime) -> Decimal:
        stmt = select(func.coalesce(func.sum(Position.realized_profit), 0)).where(
            Position.status == PositionStatus.CLOSED,
            Position.sold_at >= since,
        )
        result = await self.session.execute(stmt)
        return Decimal(result.scalar_one())

    async def count_by_status(self) -> dict[PositionStatus, int]:
        stmt = select(Position.status, func.count()).group_by(Position.status)
        result = await self.session.execute(stmt)
        return {status: count for status, count in result.all()}

    async def capital_in_open_trades(self) -> Decimal:
        stmt = select(func.coalesce(func.sum(Position.buy_price), 0)).where(Position.status.in_(ACTIVE_STATUSES))
        result = await self.session.execute(stmt)
        return Decimal(result.scalar_one())

    async def realized_profit_total(self) -> Decimal:
        stmt = select(func.coalesce(func.sum(Position.realized_profit), 0)).where(
            Position.status == PositionStatus.CLOSED
        )
        result = await self.session.execute(stmt)
        return Decimal(result.scalar_one())

    async def last_loss_at(self, pool_item_hash: str) -> Optional[datetime]:
        stmt = select(func.max(Position.sold_at)).where(
            Position.pool_item_hash == pool_item_hash,
            Position.status == PositionStatus.CLOSED,
            Position.realized_profit < 0,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def add(self, data: PositionCreate) -> Position:
        pos = Position(
            pool_item_hash=data.pool_item_hash,
            buy_order_id=data.buy_order_id,
            buy_price=data.buy_price,
            sell_price=data.sell_price,
            status=PositionStatus.OPEN,
        )
        self.session.add(pos)
        await self.session.commit()
        await self.session.refresh(pos, attribute_names=["pool_item"])
        return pos

    async def update(self, position_id: int, data: PositionUpdate) -> Position:
        values = data.model_dump(exclude_unset=True)
        if not values:
            return await self.get_by_id(position_id)

        stmt = (
            update(Position)
            .where(Position.id == position_id)
            .values(**values)
            .execution_options(synchronize_session="fetch")
        )
        await self.session.execute(stmt)
        await self.session.commit()
        return await self.get_by_id(position_id)

    async def delete(self, position_id: int) -> None:
        stmt = delete(Position).where(Position.id == position_id)
        await self.session.execute(stmt)
        await self.session.commit()
