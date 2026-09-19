from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from smt.schemas.settings import SettingsResponse, SettingsUpdate
from smt.services.dependencies import get_pool_service, get_settings_service, get_stats_refresh_service
from smt.services.market_analytics import JUDGEMENT_SETTINGS
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
    current = await service.get_settings()
    before = {name: getattr(current, name) for name in JUDGEMENT_SETTINGS}

    try:
        updated_settings = await service.update_settings(update)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

    if any(getattr(updated_settings, name) != value for name, value in before.items()):
        pool_items = await pool_service.list()
        background_tasks.add_task(refresh_service.refresh_indicators, [item.market_hash_name for item in pool_items])

    return updated_settings


@router.post("/reset", response_model=SettingsResponse)
async def reset_to_defaults(service: SettingsService = Depends(get_settings_service)):
    default_update = SettingsUpdate(
        min_profit_threshold=Decimal("0.30"),
        max_investment_per_item=Decimal("50.00"),
        buy_percentile=10,
        sell_percentile=90,
        min_volume_24h=10,
        min_volume_7d=50,
        max_volatility_threshold=Decimal("0.5000"),
        price_history_days=30,
        analysis_window_days=14,
        max_concurrent_trades=10,
        cooldown_after_loss_hours=24,
        price_refresh_interval_minutes=30,
        stats_refresh_interval_minutes=60,
        emergency_stop=False,
        cancel_untracked_orders=False,
        max_daily_loss=Decimal("100.00"),
    )
    try:
        return await service.update_settings(default_update)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
