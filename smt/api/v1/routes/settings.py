from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends

from smt.schemas.settings import SettingsResponse, SettingsUpdate
from smt.services.dependencies import get_pool_service, get_settings_service, get_stats_refresh_service
from smt.services.pool import PoolService
from smt.services.settings import SettingsService
from smt.services.stats_refresh import StatsRefreshService


router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/", response_model=SettingsResponse)
async def get_settings(service: SettingsService = Depends(get_settings_service)):
    return await service.get_settings()


@router.patch("/", response_model=SettingsResponse)
async def update_settings(
    update: SettingsUpdate,
    background_tasks: BackgroundTasks,
    service: SettingsService = Depends(get_settings_service),
    pool_service: PoolService = Depends(get_pool_service),
    refresh_service: StatsRefreshService = Depends(get_stats_refresh_service),
):
    updated_settings = await service.update_settings(update)

    # Trigger recalculation of all pool items if analytical settings changed
    analytical_fields = {
        "buy_percentile",
        "sell_percentile",
        "min_profit_threshold",
        "min_volume_24h",
        "max_volatility_threshold",
        "analysis_window_days",
    }

    if any(field in update.dict(exclude_unset=True) for field in analytical_fields):
        pool_items = await pool_service.list()
        item_names = [item.market_hash_name for item in pool_items]

        # Recalculate indicators for all items
        background_tasks.add_task(refresh_service.refresh_indicators, item_names)

    return updated_settings


@router.post("/reset", response_model=SettingsResponse)
async def reset_to_defaults(service: SettingsService = Depends(get_settings_service)):
    default_update = SettingsUpdate(
        min_profit_threshold=Decimal("0.10"),
        min_profit_percentage=Decimal("5.00"),
        max_investment_per_item=Decimal("50.00"),
        buy_percentile=20,
        sell_percentile=80,
        min_volume_24h=10,
        min_volume_7d=50,
        max_volatility_threshold=Decimal("0.5000"),
        min_volatility_threshold=Decimal("0.0100"),
        price_history_days=30,
        analysis_window_days=7,
        max_concurrent_trades=10,
        cooldown_after_loss_hours=24,
        price_refresh_interval_minutes=30,
        stats_refresh_interval_minutes=60,
        emergency_stop=False,
        max_daily_loss=Decimal("100.00"),
    )
    return await service.update_settings(default_update)
