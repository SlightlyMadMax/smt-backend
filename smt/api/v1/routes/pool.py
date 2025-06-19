from fastapi import APIRouter, BackgroundTasks, Depends

from smt.schemas.pool import (
    PoolItem,
    PoolItemBulkCreateRequest,
    PoolItemBulkCreateResponse,
    PoolItemCreateRequest,
    PoolItemStatus,
    PoolItemUpdate,
)
from smt.services.dependencies import get_pool_service, get_stats_refresh_service
from smt.services.pool import PoolService
from smt.services.stats_refresh import StatsRefreshService


router = APIRouter(prefix="/pool", tags=["pool"])


@router.get("/", response_model=list[PoolItem])
async def read_pool(service: PoolService = Depends(get_pool_service)):
    return await service.list()


@router.get("/status", response_model=list[PoolItemStatus])
async def status(market_hash_names: str, service: PoolService = Depends(get_pool_service)):
    names = market_hash_names.split(",")
    items = await service.get_many(names)
    statuses = []
    for item in items:
        statuses.append(
            PoolItemStatus(
                market_hash_name=item.market_hash_name,
                current_lowest_price=item.current_lowest_price,
                current_volume24h=item.current_volume24h,
                updated_at=item.updated_at if item.updated_at else None,
                optimal_buy_price=item.optimal_buy_price,
                optimal_sell_price=item.optimal_sell_price,
                volatility=item.volatility,
                potential_profit=item.potential_profit,
                use_for_trading=item.use_for_trading,
            )
        )
    return statuses


@router.post("/add", response_model=PoolItem)
async def add_to_pool(
    payload: PoolItemCreateRequest,
    background_tasks: BackgroundTasks,
    pool_service: PoolService = Depends(get_pool_service),
    refresh_stats_service: StatsRefreshService = Depends(get_stats_refresh_service),
):
    created = await pool_service.add_one(payload.asset_id)
    background_tasks.add_task(refresh_stats_service.refresh_price_history, [created.market_hash_name], 30)
    background_tasks.add_task(refresh_stats_service.refresh_current_stats, created.market_hash_name)
    background_tasks.add_task(refresh_stats_service.refresh_indicators, [created.market_hash_name])
    return created


@router.post("/add-multiple", response_model=PoolItemBulkCreateResponse)
async def add_multiple_to_pool(
    payload: PoolItemBulkCreateRequest,
    background_tasks: BackgroundTasks,
    pool_service: PoolService = Depends(get_pool_service),
    refresh_stats_service: StatsRefreshService = Depends(get_stats_refresh_service),
):
    pool_items = await pool_service.add_many(payload.asset_ids)
    names = [i.market_hash_name for i in pool_items]
    background_tasks.add_task(refresh_stats_service.refresh_price_history, names, 30)
    for item in pool_items:
        background_tasks.add_task(refresh_stats_service.refresh_current_stats, item.market_hash_name)
    background_tasks.add_task(refresh_stats_service.refresh_indicators, names)
    return PoolItemBulkCreateResponse(count=len(pool_items))


@router.patch("/{market_hash_name}", response_model=PoolItem)
async def update(
    market_hash_name: str,
    payload: PoolItemUpdate,
    service: PoolService = Depends(get_pool_service),
):
    updated = await service.update(market_hash_name, payload)
    return updated
