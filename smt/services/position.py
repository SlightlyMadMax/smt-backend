from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional, Sequence

from smt.db.models import Position, PositionStatus
from smt.repositories.position import PositionRepo
from smt.schemas.position import PositionCreate, PositionUpdate
from smt.utils.steam import net_received


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
        active: List[Position] = []
        for status in (
            PositionStatus.OPEN,
            PositionStatus.BOUGHT,
            PositionStatus.LISTING_PENDING,
            PositionStatus.LISTED,
        ):
            active.extend(await self.list_by_status(status=status))

        return active

    async def mark_as_bought(self, position_id: int, asset_id: str, bought_at: Optional[datetime] = None) -> Position:
        """
        Transition a Position from OPEN to BOUGHT.
        """
        pos = await self.get(position_id)
        if pos.status != PositionStatus.OPEN:
            raise ValueError("Can only mark OPEN positions as BOUGHT")
        bought_at = bought_at or datetime.now(timezone.utc)
        update_data = PositionUpdate(asset_id=asset_id, status=PositionStatus.BOUGHT.value, bought_at=bought_at)
        pos = await self.repo.update(position_id, update_data)
        return pos

    async def mark_as_listing_pending(self, position_id: int, listed_at: Optional[datetime] = None) -> Position:
        """
        Transition a Position from BOUGHT to LISTING_PENDING.

        Steam does not return a listing id when a sell order is created, so the
        position waits here until the listing shows up in the account listings.
        """
        pos = await self.get(position_id)
        if pos.status != PositionStatus.BOUGHT:
            raise ValueError("Can only mark BOUGHT positions as LISTING_PENDING")
        listed_at = listed_at or datetime.now(timezone.utc)
        update_data = PositionUpdate(status=PositionStatus.LISTING_PENDING.value, listed_at=listed_at)
        pos = await self.repo.update(position_id, update_data)
        return pos

    async def mark_as_listed(self, position_id: int, sell_order_id: str) -> Position:
        """
        Transition a Position from LISTING_PENDING to LISTED once its listing id is known.
        """
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
        """
        Transition a LISTED Position to CLOSED and record what the sale returned.

        The buyer paid `sell_price`; Steam and the publisher take their cut from it,
        so the wallet receives less. Both numbers are stored rather than recomputed
        later, because the fee model can change.
        """
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

    async def realized_profit_since(self, since: datetime) -> Decimal:
        return await self.repo.realized_profit_since(since)

    async def mark_as_cancelled(self, position_id: int) -> Position:
        """
        Transition an OPEN Position to CANCELLED.

        Used when the buy order is gone from Steam and no matching item arrived,
        which means the order expired or was cancelled rather than filled.
        """
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
