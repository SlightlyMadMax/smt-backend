from fastapi import APIRouter, BackgroundTasks, Depends

from smt.schemas.pool import (
    PoolItem,
    PoolItemBulkCreateRequest,
    PoolItemBulkCreateResponse,
    PoolItemCreateRequest,
    PoolItemStatus,
    PoolItemUpdate,
)
from smt.services.dependencies import get_pool_service
from smt.services.pool import PoolService


router = APIRouter(prefix="/pool", tags=["pool"])


@router.get("/", response_model=list[PoolItem])
async def read_pool(service: PoolService = Depends(get_pool_service)):
    return await service.list()


@router.get("/status", response_model=list[PoolItemStatus])
async def status(market_name_hashes: str, service: PoolService = Depends(get_pool_service)):
    names = market_name_hashes.split(",")
    items = await service.get_many(names)
    statuses = []
    for item in items:
        statuses.append(
            PoolItemStatus(
                market_hash_name=item.market_hash_name,
                current_lowest_price=item.current_lowest_price,
                current_volume24h=item.current_volume24h,
                updated_at=item.updated_at if item.updated_at else None,
            )
        )
    return statuses


@router.post("/add", response_model=PoolItem)
async def add_to_pool(
    payload: PoolItemCreateRequest,
    background_tasks: BackgroundTasks,
    service: PoolService = Depends(get_pool_service),
):
    created = await service.add_one(payload.asset_id)
    background_tasks.add_task(service.backfill_price_history_for, [created.market_hash_name])
    background_tasks.add_task(service.update_snapshot_for, created.market_hash_name)
    return created


@router.post("/add-multiple", response_model=PoolItemBulkCreateResponse)
async def add_multiple_to_pool(
    payload: PoolItemBulkCreateRequest,
    background_tasks: BackgroundTasks,
    service: PoolService = Depends(get_pool_service),
):
    pool_items = await service.add_many(payload.asset_ids)
    background_tasks.add_task(service.backfill_price_history_for, [i.market_hash_name for i in pool_items])
    for item in pool_items:
        background_tasks.add_task(service.update_snapshot_for, item.market_hash_name)
    return PoolItemBulkCreateResponse(count=len(pool_items))


@router.patch("/{market_hash_name}", response_model=PoolItem)
async def update(
    market_hash_name: str,
    payload: PoolItemUpdate,
    service: PoolService = Depends(get_pool_service),
):
    updated = await service.update(market_hash_name, payload)
    return updated
