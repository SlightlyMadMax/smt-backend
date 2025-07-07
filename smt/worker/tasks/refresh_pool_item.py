import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from smt.db.database import async_session_maker
from smt.logger import get_logger
from smt.repositories.items import ItemRepo
from smt.repositories.pool_items import PoolRepo
from smt.repositories.price_history import PriceHistoryRepo
from smt.repositories.settings import SettingsRepo
from smt.services.inventory import InventoryService
from smt.services.market_analytics import MarketAnalyticsService
from smt.services.pool import PoolService
from smt.services.price_history import PriceHistoryService
from smt.services.settings import SettingsService
from smt.services.stats_refresh import StatsRefreshService
from smt.services.steam import SteamService


logger = get_logger("worker.tasks")


async def build_services(session: AsyncSession, steam_service: SteamService):
    item_repo = ItemRepo(session)
    inventory_service = InventoryService(steam_service, item_repo)
    price_history_repo = PriceHistoryRepo(session)
    pool_repo = PoolRepo(session)
    settings_repo = SettingsRepo(session)

    price_history_service = PriceHistoryService(price_history_repo)
    settings_service = SettingsService(settings_repo)
    analytics_service = MarketAnalyticsService(settings_service)
    pool_service = PoolService(pool_repo, inventory_service)

    stats_service = StatsRefreshService(
        price_history_service=price_history_service,
        pool_service=pool_service,
        steam_service=steam_service,
        analytics_service=analytics_service,
        settings_service=settings_service,
    )

    return stats_service, pool_repo


async def refresh_task(ctx, market_hash_names: list[str]):
    async with async_session_maker() as session:
        try:
            stats_service, _ = await build_services(session=session, steam_service=ctx["steam_service"])

            batch_size = 10
            for i in range(0, len(market_hash_names), batch_size):
                batch = market_hash_names[i : i + batch_size]
                await stats_service.refresh_all(batch)

                if i + batch_size < len(market_hash_names):
                    await asyncio.sleep(2)

            logger.info(f"Refresh completed for {len(market_hash_names)} items")
        except Exception as e:
            logger.error(f"Background refresh failed: {e}")
            raise


async def refresh_periodic_task(ctx):
    async with async_session_maker() as session:
        try:
            stats_service, pool_repo = await build_services(session=session, steam_service=ctx["steam_service"])
            all_items = await pool_repo.list_items()
            market_hash_names = [item.market_hash_name for item in all_items]

            batch_size = 10
            for i in range(0, len(market_hash_names), batch_size):
                batch = market_hash_names[i : i + batch_size]
                await stats_service.refresh_all(batch)

                if i + batch_size < len(market_hash_names):
                    await asyncio.sleep(2)

            logger.info(f"Periodic refresh completed for {len(market_hash_names)} items")
        except Exception as e:
            logger.error(f"Periodic refresh failed: {e}")
            raise
