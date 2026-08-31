import time
from typing import Optional

from smt.logger import get_logger


logger = get_logger("worker.schedule")

KEY_PREFIX = "smt:last_run:"


async def due(redis, name: str, interval_minutes: int) -> bool:
    """Whether a periodic job should run now, given how long ago it last ran."""
    if interval_minutes <= 0:
        return True

    key = f"{KEY_PREFIX}{name}"
    now = time.time()
    last: Optional[bytes] = await redis.get(key)

    if last is not None:
        elapsed = now - float(last)
        if elapsed < interval_minutes * 60:
            logger.debug(f"{name} ran {elapsed / 60:.1f} min ago, waiting for {interval_minutes} min.")
            return False

    await redis.set(key, now)
    return True
