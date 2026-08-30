import asyncio
import time
from collections import deque


class RateLimiter:
    """
    Sliding window limiter: at most `max_calls` acquisitions in any `period` seconds.

    Waiters are serialised on a lock, so they are admitted in the order they arrived.
    """

    def __init__(self, max_calls: int, period: float):
        if max_calls < 1:
            raise ValueError("max_calls must be at least 1")
        if period <= 0:
            raise ValueError("period must be positive")

        self._max_calls = max_calls
        self._period = period
        self._calls: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                cutoff = now - self._period
                while self._calls and self._calls[0] <= cutoff:
                    self._calls.popleft()

                if len(self._calls) < self._max_calls:
                    self._calls.append(now)
                    return

                await asyncio.sleep(self._calls[0] + self._period - now)
