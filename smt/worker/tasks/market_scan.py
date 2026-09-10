from smt.logger import get_logger
from smt.services.market_scan import MarketScanService, ScanParams
from smt.services.steam import SteamService


logger = get_logger("worker.tasks")


async def market_scan_task(ctx, scan_id: str, params: dict) -> None:
    steam: SteamService = ctx["steam_service"]
    service = MarketScanService(steam, steam._redis)

    logger.info(f"Starting market scan {scan_id} with {params}")
    await service.run(scan_id, ScanParams.from_dict(params))
    logger.info(f"Market scan {scan_id} finished")
