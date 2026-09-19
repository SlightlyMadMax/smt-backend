from datetime import datetime
from decimal import Decimal
from typing import Optional, Sequence

from sqlalchemy import delete, func, nulls_last, select, update
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from smt.db.models import PoolItem, Position
from smt.schemas.position import (
    ACTIVE_STATUSES,
    PositionCreate,
    PositionSortKey,
    PositionStatus,
    PositionUpdate,
    SortOrder,
)


SORT_COLUMNS = {
    PositionSortKey.NAME: PoolItem.name,
    PositionSortKey.STATUS: Position.status,
    PositionSortKey.BUY_PRICE: Position.buy_price,
    PositionSortKey.SELL_PRICE: Position.sell_price,
    PositionSortKey.NET_PROCEEDS: Position.net_proceeds,
    PositionSortKey.REALIZED_PROFIT: Position.realized_profit,
    PositionSortKey.CREATED_AT: Position.created_at,
    PositionSortKey.BOUGHT_AT: Position.bought_at,
    PositionSortKey.LISTED_AT: Position.listed_at,
    PositionSortKey.SOLD_AT: Position.sold_at,
}


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

    async def list_page(
        self,
        limit: int,
        offset: int,
        status: Optional[PositionStatus] = None,
        sort: PositionSortKey = PositionSortKey.CREATED_AT,
        order: SortOrder = SortOrder.DESC,
    ) -> Sequence[Position]:
        stmt = select(Position).options(selectinload(Position.pool_item))
        if status:
            stmt = stmt.where(Position.status == status)

        column = SORT_COLUMNS[sort]
        if sort is PositionSortKey.NAME:
            stmt = stmt.outerjoin(PoolItem, Position.pool_item_hash == PoolItem.market_hash_name)

        direction = column.asc() if order is SortOrder.ASC else column.desc()
        stmt = stmt.order_by(nulls_last(direction), Position.id.desc()).limit(limit).offset(offset)

        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count(self, status: Optional[PositionStatus] = None) -> int:
        stmt = select(func.count()).select_from(Position)
        if status:
            stmt = stmt.where(Position.status == status)
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

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
            app_id=data.app_id,
            context_id=data.context_id,
            buy_order_id=data.buy_order_id,
            buy_price=data.buy_price,
            sell_price=data.sell_price,
            forecast_profit=data.forecast_profit,
            forecast_hold_hours=data.forecast_hold_hours,
            forecast_days_to_clear=data.forecast_days_to_clear,
            forecast_return_30d=data.forecast_return_30d,
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
