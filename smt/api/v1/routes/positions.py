from typing import Optional

from fastapi import APIRouter, Depends, Query

from smt.schemas.position import (
    PositionPage,
    PositionRow,
    PositionSortKey,
    PositionStatus,
    PositionSummary,
    SortOrder,
)
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


@router.get("/", response_model=PositionPage)
async def read_positions(
    status: Optional[PositionStatus] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    sort: PositionSortKey = Query(PositionSortKey.CREATED_AT),
    order: SortOrder = Query(SortOrder.DESC),
    service: PositionService = Depends(get_position_service),
):
    positions = await service.list_page(limit=limit, offset=offset, status=status, sort=sort, order=order)
    return PositionPage(items=[to_row(p) for p in positions], total=await service.count(status))


@router.get("/summary", response_model=PositionSummary)
async def read_summary(service: PositionService = Depends(get_position_service)):
    return PositionSummary(**await service.summary())
