from fastapi import Depends

from smt.repositories.dependencies import get_item_repo, get_pool_repo, get_stat_repo
from smt.services.inventory import InventoryService
from smt.services.pool import PoolService
from smt.services.stats import StatService
from smt.services.steam import SteamService


def get_pool_service(
    item_repo=Depends(get_item_repo),
    pool_repo=Depends(get_pool_repo),
    stat_repo=Depends(get_stat_repo),
    steam=Depends(SteamService),
):
    return PoolService(item_repo, pool_repo, stat_repo, steam)


def get_inventory_service(
    steam=Depends(SteamService),
    item_repo=Depends(get_item_repo),
):
    return InventoryService(steam, item_repo)


def get_stats_service(
    stat_repo=Depends(get_stat_repo),
):
    return StatService(stat_repo)
