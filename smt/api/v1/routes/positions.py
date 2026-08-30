from typing import List, Optional

from fastapi import APIRouter, Depends, Query

from smt.schemas.position import PositionRow, PositionStatus, PositionSummary
from smt.services.dependencies import get_position_service
from smt.services.position import PositionService


router = APIRouter(prefix="/positions", tags=["positions"])


def to_row(position) -> PositionRow:
    item = position.pool_item
    return PositionRow(
        id=position.id,
        pool_item_hash=position.pool_item_hash,
        name=item.name if item else position.pool_item_hash,
        icon_url=item.icon_url if item else "",
        listing_url=item.listing_url if item else "",
        status=position.status,
        buy_price=position.buy_price,
        sell_price=position.sell_price,
        net_proceeds=position.net_proceeds,
        realized_profit=position.realized_profit,
        bought_at=position.bought_at,
        listed_at=position.listed_at,
        sold_at=position.sold_at,
        created_at=position.created_at,
    )


@router.get("/", response_model=List[PositionRow])
async def read_positions(
    status: Optional[PositionStatus] = Query(None),
    service: PositionService = Depends(get_position_service),
):
    positions = await service.list_by_status(status) if status else await service.list()
    return [to_row(p) for p in sorted(positions, key=lambda p: p.created_at, reverse=True)]


@router.get("/summary", response_model=PositionSummary)
async def read_summary(service: PositionService = Depends(get_position_service)):
    return PositionSummary(**await service.summary())
