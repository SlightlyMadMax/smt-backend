from functools import lru_cache

from fastapi import Depends

from smt.core.config import Settings, get_settings
from smt.repositories.dependencies import (
    get_item_repo,
    get_pool_repo,
    get_position_repo,
    get_price_history_repo,
    get_settings_repo,
)
from smt.services.inventory import InventoryService
from smt.services.market_analytics import MarketAnalyticsService
from smt.services.pool import PoolService
from smt.services.position import PositionService
from smt.services.price_history import PriceHistoryService
from smt.services.settings import SettingsService
from smt.services.stats_refresh import StatsRefreshService
from smt.services.steam import SteamService


@lru_cache()
def get_steam_service(settings: Settings = Depends(get_settings)) -> SteamService:
    return SteamService(settings)


def get_inventory_service(
    steam=Depends(get_steam_service),
    item_repo=Depends(get_item_repo),
) -> InventoryService:
    return InventoryService(steam, item_repo)


def get_price_history_service(
    price_history_repo=Depends(get_price_history_repo),
) -> PriceHistoryService:
    return PriceHistoryService(price_history_repo)


def get_pool_service(
    item_repo=Depends(get_item_repo),
    pool_repo=Depends(get_pool_repo),
) -> PoolService:
    return PoolService(item_repo, pool_repo)


def get_settings_service(settings_repo=Depends(get_settings_repo)) -> SettingsService:
    return SettingsService(settings_repo)


def get_market_analytics_service(settings_service=Depends(get_settings_service)) -> MarketAnalyticsService:
    return MarketAnalyticsService(settings_service)


def get_stats_refresh_service(
    pool_service=Depends(get_pool_service),
    price_history_service=Depends(get_price_history_service),
    steam=Depends(get_steam_service),
    analytics_service=Depends(get_market_analytics_service),
    settings_service=Depends(get_settings_service),
) -> StatsRefreshService:
    return StatsRefreshService(price_history_service, pool_service, steam, analytics_service, settings_service)


def get_position_service(position_repo=Depends(get_position_repo)) -> PositionService:
    return PositionService(position_repo)
