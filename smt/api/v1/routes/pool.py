from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from starlette.responses import Response

from smt.schemas.pool import (
    PoolItem,
    PoolItemBulkCreateRequest,
    PoolItemBulkCreateResponse,
    PoolItemBulkRefreshRequest,
    PoolItemCreateRequest,
    PoolItemStatus,
    PoolItemUpdate,
    RemoveManyRequest,
    RemoveManyResponse,
    RemoveResponse,
)
from smt.services.dependencies import get_pool_service
from smt.services.pool import PoolService
from smt.tasks.refresh_pool_item import background_refresh_task


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
):
    created = await pool_service.add_one(payload.asset_id)
    background_tasks.add_task(background_refresh_task, [created.market_hash_name])
    return created


@router.post("/add-multiple", response_model=PoolItemBulkCreateResponse)
async def add_multiple_to_pool(
    payload: PoolItemBulkCreateRequest,
    background_tasks: BackgroundTasks,
    pool_service: PoolService = Depends(get_pool_service),
):
    pool_items = await pool_service.add_many(payload.asset_ids)
    names = [i.market_hash_name for i in pool_items]
    background_tasks.add_task(background_refresh_task, names)
    return PoolItemBulkCreateResponse(count=len(pool_items))


@router.patch("/{market_hash_name}", response_model=PoolItem)
async def update(
    market_hash_name: str,
    payload: PoolItemUpdate,
    service: PoolService = Depends(get_pool_service),
):
    updated = await service.update(market_hash_name, payload)
    return updated


@router.delete("/{market_hash_name}", response_model=RemoveResponse)
async def remove_pool_item(market_hash_name: str, service: PoolService = Depends(get_pool_service)) -> RemoveResponse:
    try:
        success = await service.remove(market_hash_name)

        if success:
            return RemoveResponse(success=True, message=f"Pool item '{market_hash_name}' removed successfully")
        else:
            return RemoveResponse(success=False, message=f"Pool item '{market_hash_name}' not found")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to remove pool item: {str(e)}"
        )


@router.delete("/", response_model=RemoveManyResponse)
async def remove_many_pool_items(
    request: RemoveManyRequest, service: PoolService = Depends(get_pool_service)
) -> RemoveManyResponse:
    try:
        if not request.market_hash_names:
            return RemoveManyResponse(removed_count=0, message="No items specified for removal")

        removed_count = await service.remove_many(request.market_hash_names)

        total_requested = len(request.market_hash_names)

        if removed_count == 0:
            message = "No items were removed (none found)"
        elif removed_count == total_requested:
            message = f"All {removed_count} items removed successfully"
        else:
            message = f"{removed_count} out of {total_requested} items removed successfully"

        return RemoveManyResponse(removed_count=removed_count, message=message)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to remove pool items: {str(e)}"
        )


@router.post("/refresh/{market_hash_name}", status_code=204)
async def refresh(
    market_hash_name: str,
    background_tasks: BackgroundTasks,
):
    background_tasks.add_task(background_refresh_task, [market_hash_name])
    return Response(status_code=204)


@router.post("/refresh-many", status_code=204)
async def refresh_many(
    payload: PoolItemBulkRefreshRequest,
    background_tasks: BackgroundTasks,
):
    background_tasks.add_task(background_refresh_task, payload.market_hash_names)
    return Response(status_code=204)
