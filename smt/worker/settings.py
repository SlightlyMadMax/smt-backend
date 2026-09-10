from arq import cron
from arq.connections import RedisSettings

from smt.core.config import get_settings
from smt.logger import get_logger, setup_all_loggers
from smt.services.steam import SteamService
from smt.worker.tasks.market_scan import market_scan_task
from smt.worker.tasks.refresh_pool_item import refresh_periodic_task, refresh_task
from smt.worker.tasks.trading_cycle import trading_cycle


settings = get_settings()
logger = get_logger("worker")


async def startup(ctx) -> None:
    setup_all_loggers()
    ctx["steam_service"] = SteamService(settings)
    logger.info("Worker started")


async def shutdown(ctx) -> None:
    logger.info("Worker stopped")


class WorkerSettings:
    functions = [refresh_task, market_scan_task]
    cron_jobs = [
        cron(refresh_periodic_task, hour=None, minute=set(range(0, 60, 5)), second=30),
        cron(trading_cycle, hour=None, minute=set(range(5, 60, 5)), second=0),
    ]
    redis_settings = RedisSettings(
        host=settings.REDIS_HOST,
        port=int(settings.REDIS_PORT),
        password=settings.REDIS_PASSWORD,
    )
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 1
