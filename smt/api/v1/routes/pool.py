from fastapi import APIRouter, Depends, HTTPException, status
from starlette.responses import Response

from smt.exceptions import OrderBookUnavailable, SteamLoginUnavailable
from smt.schemas.pool import (
    OrderBook,
    PoolItem,
    PoolItemBulkCreateRequest,
    PoolItemBulkCreateResponse,
    PoolItemBulkRefreshRequest,
    PoolItemCreateRequest,
    PoolItemStatus,
    PoolItemUpdate,
    PoolSummary,
    RemoveManyRequest,
    RemoveManyResponse,
    RemoveResponse,
    TradingToggle,
)
from smt.schemas.settings import SettingsUpdate
from smt.services.dependencies import get_pool_service, get_settings_service, get_steam_service
from smt.services.pool import PoolService
from smt.services.settings import SettingsService
from smt.services.steam import SteamService
from smt.worker.arq import ARQService, get_arq_service


router = APIRouter(prefix="/pool", tags=["pool"])


@router.get("/", response_model=list[PoolItem])
async def read_pool(service: PoolService = Depends(get_pool_service)):
    return await service.list()


@router.get("/summary", response_model=PoolSummary)
async def read_pool_summary(
    pool_service: PoolService = Depends(get_pool_service),
    settings_service: SettingsService = Depends(get_settings_service),
):
    settings = await settings_service.get_settings()
    return PoolSummary(**await pool_service.summary(), trading_enabled=not settings.emergency_stop)


@router.patch("/trading", response_model=PoolSummary)
async def set_trading_enabled(
    payload: TradingToggle,
    pool_service: PoolService = Depends(get_pool_service),
    settings_service: SettingsService = Depends(get_settings_service),
):
    await settings_service.update_settings(SettingsUpdate(emergency_stop=not payload.enabled))
    return PoolSummary(**await pool_service.summary(), trading_enabled=payload.enabled)


@router.get("/status", response_model=list[PoolItemStatus])
async def read_status(market_hash_names: str, service: PoolService = Depends(get_pool_service)):
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
                effective_buy_price=item.effective_buy_price,
                effective_sell_price=item.effective_sell_price,
                manual_buy_price=item.manual_buy_price,
                manual_sell_price=item.manual_sell_price,
                max_listed=item.max_listed,
                current_highest_buy_order=item.current_highest_buy_order,
                current_volume7d=item.current_volume7d,
                round_trips=item.round_trips,
                median_hold_hours=item.median_hold_hours,
                return_on_capital_30d=item.return_on_capital_30d,
            )
        )
    return statuses


@router.get("/{market_hash_name}/order-book", response_model=OrderBook)
async def read_order_book(
    market_hash_name: str,
    pool_service: PoolService = Depends(get_pool_service),
    steam: SteamService = Depends(get_steam_service),
):
    item = await pool_service.get_by_market_hash_name(market_hash_name)
    try:
        return OrderBook(**await steam.get_order_book(market_hash_name=market_hash_name, app_id=item.app_id))
    except (OrderBookUnavailable, SteamLoginUnavailable) as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))


@router.post("/add", response_model=PoolItem)
async def add_to_pool(
    payload: PoolItemCreateRequest,
    pool_service: PoolService = Depends(get_pool_service),
    arq_service: ARQService = Depends(get_arq_service),
):
    created = await pool_service.add_one(payload.asset_id)
    await arq_service.enqueue("refresh_task", [created.market_hash_name])
    return created


@router.post("/add-multiple", response_model=PoolItemBulkCreateResponse)
async def add_multiple_to_pool(
    payload: PoolItemBulkCreateRequest,
    pool_service: PoolService = Depends(get_pool_service),
    arq_service: ARQService = Depends(get_arq_service),
):
    pool_items = await pool_service.add_many(payload.asset_ids)
    names = [i.market_hash_name for i in pool_items]
    await arq_service.enqueue("refresh_task", names)
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
    arq_service: ARQService = Depends(get_arq_service),
):
    await arq_service.enqueue("refresh_task", [market_hash_name])
    return Response(status_code=204)


@router.post("/refresh-many", status_code=204)
async def refresh_many(
    payload: PoolItemBulkRefreshRequest,
    arq_service: ARQService = Depends(get_arq_service),
):
    await arq_service.enqueue("refresh_task", payload.market_hash_names)
    return Response(status_code=204)
