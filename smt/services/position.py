from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Optional, Sequence

from smt.db.models import Position, PositionStatus
from smt.repositories.position import PositionRepo
from smt.schemas.position import ACTIVE_STATUSES, PositionCreate, PositionUpdate
from smt.utils.steam import net_received


class PositionService:
    def __init__(self, repo: PositionRepo):
        self.repo = repo

    async def add(
        self,
        data: PositionCreate,
    ) -> Position:
        """Create a new Position in OPEN state using PositionCreate schema."""
        pos = await self.repo.add(data)
        return pos

    async def list(self) -> Sequence[Position]:
        return await self.repo.list()

    async def list_by_status(self, status: PositionStatus) -> Sequence[Position]:
        return await self.repo.list_by_status(status=status)

    async def list_active(self) -> List[Position]:
        active: List[Position] = []
        for status in ACTIVE_STATUSES:
            active.extend(await self.list_by_status(status=status))

        return active

    async def list_page(self, **kwargs) -> Sequence[Position]:
        return await self.repo.list_page(**kwargs)

    async def count(self, status: Optional[PositionStatus] = None) -> int:
        return await self.repo.count(status)

    async def summary(self) -> dict:
        counts = await self.repo.count_by_status()
        return {
            "counts": {status.value: counts.get(status, 0) for status in PositionStatus},
            "active_count": sum(counts.get(status, 0) for status in ACTIVE_STATUSES),
            "capital_in_open_trades": await self.repo.capital_in_open_trades(),
            "realized_profit_24h": await self.repo.realized_profit_since(
                datetime.now(timezone.utc) - timedelta(days=1)
            ),
            "realized_profit_total": await self.repo.realized_profit_total(),
        }

    async def mark_as_bought(self, position_id: int, asset_id: str, bought_at: Optional[datetime] = None) -> Position:
        """Transition a Position from OPEN to BOUGHT."""
        pos = await self.get(position_id)
        if pos.status != PositionStatus.OPEN:
            raise ValueError("Can only mark OPEN positions as BOUGHT")
        bought_at = bought_at or datetime.now(timezone.utc)
        update_data = PositionUpdate(asset_id=asset_id, status=PositionStatus.BOUGHT.value, bought_at=bought_at)
        pos = await self.repo.update(position_id, update_data)
        return pos

    async def mark_as_listing_pending(self, position_id: int, listed_at: Optional[datetime] = None) -> Position:
        """Transition a Position from BOUGHT to LISTING_PENDING."""
        pos = await self.get(position_id)
        if pos.status != PositionStatus.BOUGHT:
            raise ValueError("Can only mark BOUGHT positions as LISTING_PENDING")
        listed_at = listed_at or datetime.now(timezone.utc)
        update_data = PositionUpdate(status=PositionStatus.LISTING_PENDING.value, listed_at=listed_at)
        pos = await self.repo.update(position_id, update_data)
        return pos

    async def mark_as_listed(self, position_id: int, sell_order_id: str) -> Position:
        """Transition a Position from LISTING_PENDING to LISTED once its listing id is known."""
        pos = await self.get(position_id)
        if pos.status != PositionStatus.LISTING_PENDING:
            raise ValueError("Can only mark LISTING_PENDING positions as LISTED")
        update_data = PositionUpdate(sell_order_id=sell_order_id, status=PositionStatus.LISTED.value)
        pos = await self.repo.update(position_id, update_data)
        return pos

    async def close(
        self,
        position_id: int,
        sold_at: Optional[datetime] = None,
    ) -> Position:
        """Transition a LISTED Position to CLOSED and record what the sale returned."""
        pos = await self.get(position_id)
        if pos.status != PositionStatus.LISTED:
            raise ValueError("Can only close positions that are LISTED")

        sold_at = sold_at or datetime.now(timezone.utc)
        net_proceeds = net_received(pos.sell_price)

        update_data = PositionUpdate(
            status=PositionStatus.CLOSED.value,
            sold_at=sold_at,
            net_proceeds=net_proceeds,
            realized_profit=net_proceeds - pos.buy_price,
        )
        pos = await self.repo.update(position_id, update_data)
        return pos

    async def last_loss_at(self, pool_item_hash: str) -> Optional[datetime]:
        return await self.repo.last_loss_at(pool_item_hash)

    async def realized_profit_since(self, since: datetime) -> Decimal:
        return await self.repo.realized_profit_since(since)

    async def mark_as_cancelled(self, position_id: int) -> Position:
        """Transition an OPEN Position to CANCELLED."""
        pos = await self.get(position_id)
        if pos.status != PositionStatus.OPEN:
            raise ValueError("Can only cancel OPEN positions")
        update_data = PositionUpdate(status=PositionStatus.CANCELLED.value)
        pos = await self.repo.update(position_id, update_data)
        return pos

    async def get(self, position_id: int) -> Position:
        pos = await self.repo.get_by_id(position_id)
        return pos

    async def delete(self, position_id: int) -> None:
        await self.repo.delete(position_id)
