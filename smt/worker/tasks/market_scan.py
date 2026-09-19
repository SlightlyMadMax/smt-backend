from smt.db.database import async_session_maker
from smt.logger import get_logger
from smt.repositories.settings import SettingsRepo
from smt.services.market_analytics import MarketAnalyticsService
from smt.services.market_scan import MarketScanService, ScanParams
from smt.services.settings import SettingsService
from smt.services.steam import SteamService


logger = get_logger("worker.tasks")


async def market_scan_task(ctx, scan_id: str, params: dict) -> None:
    steam: SteamService = ctx["steam_service"]

    async with async_session_maker() as session:
        settings_service = SettingsService(SettingsRepo(session))
        service = MarketScanService(steam, steam._redis, MarketAnalyticsService(settings_service), settings_service)

        logger.info(f"Starting market scan {scan_id} with {params}")
        await service.run(scan_id, ScanParams.from_dict(params))
        logger.info(f"Market scan {scan_id} finished")
