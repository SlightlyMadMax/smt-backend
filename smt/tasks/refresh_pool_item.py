import asyncio

from smt.core.config import get_settings
from smt.db.database import async_session_maker
from smt.logger import logger
from smt.repositories.items import ItemRepo
from smt.repositories.pool_items import PoolRepo
from smt.repositories.price_history import PriceHistoryRepo
from smt.repositories.settings import SettingsRepo
from smt.services.dependencies import get_steam_service
from smt.services.market_analytics import MarketAnalyticsService
from smt.services.pool import PoolService
from smt.services.price_history import PriceHistoryService
from smt.services.settings import SettingsService
from smt.services.stats_refresh import StatsRefreshService


async def background_refresh_task(market_hash_names: list[str]):
    async with async_session_maker() as session:
        try:
            settings = get_settings()

            item_repo = ItemRepo(session)
            price_history_repo = PriceHistoryRepo(session)
            pool_repo = PoolRepo(session)
            settings_repo = SettingsRepo(session)

            steam_service = get_steam_service(settings)
            price_history_service = PriceHistoryService(price_history_repo)
            settings_service = SettingsService(settings_repo)
            analytics_service = MarketAnalyticsService(settings_service)
            pool_service = PoolService(item_repo, pool_repo)

            stats_service = StatsRefreshService(
                price_history_service=price_history_service,
                pool_service=pool_service,
                steam_service=steam_service,
                analytics_service=analytics_service,
                settings_service=settings_service,
            )

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
