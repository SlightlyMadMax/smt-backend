import asyncio

from celery import shared_task

from smt.core.config import get_settings
from smt.db.dependencies import get_db
from smt.repositories.items import ItemRepo
from smt.repositories.pool_items import PoolRepo
from smt.repositories.price_history import PriceHistoryRepo
from smt.services.pool import PoolService
from smt.services.price_history import PriceHistoryService
from smt.services.steam import SteamService


@shared_task(name="smt.backfill_price_history_batch")
def backfill_price_history_batch(market_hash_names: list[str]):
    settings = get_settings()
    steam = SteamService(settings)

    async def _worker():
        async with get_db() as session:
            item_repo = ItemRepo(session)
            pool_repo = PoolRepo(session)
            price_history_repo = PriceHistoryRepo(session)
            hist_service = PriceHistoryService(price_history_repo)
            service = PoolService(item_repo, pool_repo, hist_service, steam)

            await service.backfill_price_history_for(market_hash_names)

    asyncio.run(_worker())


@shared_task(name="smt.update_pool_item_snapshot")
def update_pool_item_snapshot(market_hash_name: str):
    settings = get_settings()
    steam = SteamService(settings)

    async def _worker():
        async with get_db() as session:
            item_repo = ItemRepo(session)
            pool_repo = PoolRepo(session)
            price_history_repo = PriceHistoryRepo(session)
            hist_service = PriceHistoryService(price_history_repo)
            service = PoolService(item_repo, pool_repo, hist_service, steam)

            await service.update_snapshot_for(market_hash_name)

    asyncio.run(_worker())
