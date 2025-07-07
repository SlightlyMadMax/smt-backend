from sqlalchemy.ext.asyncio import AsyncSession

from smt.db.database import async_session_maker
from smt.logger import get_logger
from smt.repositories.items import ItemRepo
from smt.repositories.pool_items import PoolRepo
from smt.repositories.position import PositionRepo
from smt.repositories.settings import SettingsRepo
from smt.services.inventory import InventoryService
from smt.services.pool import PoolService
from smt.services.position import PositionService
from smt.services.settings import SettingsService
from smt.services.steam import SteamService
from smt.services.trading import TradingService


logger = get_logger("worker.tasks")


async def build_trading_service(session: AsyncSession, steam_service: SteamService):
    item_repo = ItemRepo(session)
    inventory_service = InventoryService(steam=steam_service, item_repo=item_repo)
    pool_repo = PoolRepo(session)
    settings_repo = SettingsRepo(session)
    position_repo = PositionRepo(session)

    settings_service = SettingsService(settings_repo)
    pool_service = PoolService(pool_repo, inventory_service)
    position_service = PositionService(position_repo)
    trading_service = TradingService(
        steam_service=steam_service,
        inventory_service=inventory_service,
        position_service=position_service,
        pool_item_service=pool_service,
        settings_service=settings_service,
    )

    return trading_service


async def trading_cycle(ctx):
    async with async_session_maker() as session:
        trading_service = await build_trading_service(session=session, steam_service=ctx["steam_service"])
        await trading_service.run_cycle()
