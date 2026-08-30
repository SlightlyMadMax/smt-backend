import asyncio
import time

import pytest

from smt.utils.rate_limit import RateLimiter


@pytest.mark.asyncio
class TestRateLimiter:
    async def test_allows_a_full_window_without_waiting(self):
        limiter = RateLimiter(max_calls=5, period=10)
        start = time.monotonic()

        for _ in range(5):
            await limiter.acquire()

        assert time.monotonic() - start < 0.1

    async def test_blocks_once_the_window_is_full(self):
        limiter = RateLimiter(max_calls=2, period=0.3)
        start = time.monotonic()

        for _ in range(3):
            await limiter.acquire()

        assert time.monotonic() - start >= 0.3

    async def test_slots_free_up_once_the_window_passes(self):
        limiter = RateLimiter(max_calls=2, period=0.3)
        for _ in range(2):
            await limiter.acquire()

        await asyncio.sleep(0.35)

        start = time.monotonic()
        for _ in range(2):
            await limiter.acquire()

        assert time.monotonic() - start < 0.1

    async def test_concurrent_callers_are_all_admitted(self):
        limiter = RateLimiter(max_calls=3, period=0.2)
        order = []

        async def worker(n):
            await limiter.acquire()
            order.append(n)

        await asyncio.gather(*(worker(n) for n in range(6)))

        assert sorted(order) == list(range(6))

    async def test_rejects_a_nonsense_configuration(self):
        with pytest.raises(ValueError):
            RateLimiter(max_calls=0, period=10)
        with pytest.raises(ValueError):
            RateLimiter(max_calls=1, period=0)
