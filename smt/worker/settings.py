from arq import cron
from arq.connections import RedisSettings

from smt.core.config import get_settings
from smt.logger import get_logger
from smt.services.steam import SteamService
from smt.worker.tasks.refresh_pool_item import refresh_periodic_task, refresh_task


settings = get_settings()
logger = get_logger("worker")


async def startup(ctx) -> None:
    ctx["steam_service"] = SteamService(settings)
    logger.info("Worker started")


async def shutdown(ctx) -> None:
    logger.info("Worker stopped")


class WorkerSettings:
    functions = [refresh_task]
    cron_jobs = [cron(refresh_periodic_task, minute=0, second=0)]
    redis_settings = RedisSettings(host=settings.REDIS_HOST, port=int(settings.REDIS_PORT))
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 1
