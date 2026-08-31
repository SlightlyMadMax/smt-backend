import asyncio
import time
import uuid


class RedisRateLimiter:
    """
    Sliding window shared by every process that talks to Steam.

    Holding the window in Redis rather than in the process matters twice over: the web
    app and the worker draw from one budget instead of a full one each, and a restart no
    longer forgets the calls already spent.

    The check and the reservation happen inside one Lua script so two processes cannot
    both see the last free slot.
    """

    ACQUIRE = """
    local key = KEYS[1]
    local now = tonumber(ARGV[1])
    local window = tonumber(ARGV[2])
    local limit = tonumber(ARGV[3])
    local member = ARGV[4]

    redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)

    if redis.call('ZCARD', key) < limit then
        redis.call('ZADD', key, now, member)
        redis.call('PEXPIRE', key, math.ceil(window * 1000))
        return '0'
    end

    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    return tostring(tonumber(oldest[2]) + window - now)
    """

    def __init__(self, redis, key: str, max_calls: int, period: float):
        if max_calls < 1:
            raise ValueError("max_calls must be at least 1")
        if period <= 0:
            raise ValueError("period must be positive")

        self._redis = redis
        self._key = key
        self._max_calls = max_calls
        self._period = period

    async def acquire(self) -> None:
        while True:
            wait_for = float(
                await self._redis.eval(
                    self.ACQUIRE,
                    1,
                    self._key,
                    time.time(),
                    self._period,
                    self._max_calls,
                    uuid.uuid4().hex,
                )
            )
            if wait_for <= 0:
                return

            await asyncio.sleep(wait_for)
