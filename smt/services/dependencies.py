from functools import lru_cache

from fastapi import Depends

from smt.core.config import Settings, get_settings
from smt.repositories.dependencies import get_item_repo, get_pool_repo, get_stat_repo
from smt.services.inventory import InventoryService
from smt.services.pool import PoolService
from smt.services.stats import StatService
from smt.services.steam import SteamService


@lru_cache()
def get_steam_service(settings: Settings = Depends(get_settings)) -> SteamService:
    return SteamService(settings)


def get_inventory_service(
    steam=Depends(get_steam_service),
    item_repo=Depends(get_item_repo),
) -> InventoryService:
    return InventoryService(steam, item_repo)


def get_stats_service(
    stat_repo=Depends(get_stat_repo),
) -> StatService:
    return StatService(stat_repo)


def get_pool_service(
    item_repo=Depends(get_item_repo),
    pool_repo=Depends(get_pool_repo),
    stat_service=Depends(get_stats_service),
    steam=Depends(get_steam_service),
) -> PoolService:
    return PoolService(item_repo, pool_repo, stat_service, steam)
