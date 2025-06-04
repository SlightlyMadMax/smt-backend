import asyncio

from celery import shared_task

from smt.core.config import get_settings
from smt.db.database import async_session_maker
from smt.repositories.pool_items import PoolRepo
from smt.repositories.price_history import PriceHistoryRepo
from smt.services.price_history import PriceHistoryService
from smt.services.steam import SteamService
from smt.utils.price_history import backfill_price_history_for, update_snapshot_for


@shared_task(ack_late=True)
def backfill_price_history_batch(market_hash_names: list[str]):
    settings = get_settings()
    steam = SteamService(settings)

    async def _worker():
        async with async_session_maker() as session:
            pool_repo = PoolRepo(session)
            price_history_repo = PriceHistoryRepo(session)
            hist_service = PriceHistoryService(price_history_repo)

            await backfill_price_history_for(pool_repo, steam, hist_service, market_hash_names)

    asyncio.run(_worker())


@shared_task(ack_late=True)
def update_pool_item_snapshot(market_hash_name: str):
    settings = get_settings()
    steam = SteamService(settings)

    async def _worker():
        async with async_session_maker() as session:
            pool_repo = PoolRepo(session)
            await update_snapshot_for(pool_repo, steam, market_hash_name)

    asyncio.run(_worker())
