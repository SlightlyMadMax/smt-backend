"""These run against the Redis the application actually uses."""

import asyncio
import datetime
import time
import uuid

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from smt.core.config import get_settings
from smt.exceptions import SteamLoginUnavailable, SteamThrottled
from smt.services.steam import (
    COOLDOWN_BASE,
    COOLDOWN_KEY,
    LOGIN_BLOCK_KEY,
    LOGIN_FAILURES_KEY,
    REFUSAL_COUNT_KEY,
    SteamService,
)
from smt.utils.rate_limit import RedisRateLimiter


@pytest_asyncio.fixture
async def redis():
    settings = get_settings()
    client = Redis(host=settings.REDIS_HOST, port=int(settings.REDIS_PORT), password=settings.REDIS_PASSWORD)
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def key(redis):
    name = f"smt:test:{uuid.uuid4().hex}"
    yield name
    await redis.delete(name)


@pytest.mark.asyncio
class TestRedisRateLimiter:
    async def test_allows_a_full_window_without_waiting(self, redis, key):
        limiter = RedisRateLimiter(redis, key, max_calls=5, period=10)
        started = time.monotonic()

        for _ in range(5):
            await limiter.acquire()

        assert time.monotonic() - started < 0.5

    async def test_blocks_once_the_window_is_full(self, redis, key):
        limiter = RedisRateLimiter(redis, key, max_calls=2, period=1)
        started = time.monotonic()

        for _ in range(3):
            await limiter.acquire()

        # the window opens at the first acquire, a moment after `started`
        assert time.monotonic() - started >= 0.9

    async def test_slots_free_up_once_the_window_passes(self, redis, key):
        limiter = RedisRateLimiter(redis, key, max_calls=2, period=0.5)
        for _ in range(2):
            await limiter.acquire()

        await asyncio.sleep(0.6)
        started = time.monotonic()
        for _ in range(2):
            await limiter.acquire()

        assert time.monotonic() - started < 0.5

    async def test_separate_instances_share_one_budget(self, redis, key):
        """Two limiters on the same key stand in for the web app and the worker."""
        web = RedisRateLimiter(redis, key, max_calls=2, period=1)
        worker = RedisRateLimiter(redis, key, max_calls=2, period=1)

        await web.acquire()
        await worker.acquire()

        started = time.monotonic()
        await worker.acquire()

        # the window opened at the first acquire, a moment before `started`
        assert time.monotonic() - started >= 0.9

    async def test_concurrent_callers_never_exceed_the_limit(self, redis, key):
        limiter = RedisRateLimiter(redis, key, max_calls=3, period=30)
        admitted = []

        async def caller(n):
            await limiter.acquire()
            admitted.append(n)

        # four callers, three slots: the fourth must still be waiting
        tasks = [asyncio.create_task(caller(n)) for n in range(4)]
        await asyncio.sleep(0.5)

        assert len(admitted) == 3
        for task in tasks:
            task.cancel()

    async def test_rejects_a_nonsense_configuration(self, redis, key):
        with pytest.raises(ValueError):
            RedisRateLimiter(redis, key, max_calls=0, period=10)
        with pytest.raises(ValueError):
            RedisRateLimiter(redis, key, max_calls=1, period=0)


@pytest_asyncio.fixture
async def steam_service(redis, monkeypatch):
    monkeypatch.setattr("smt.services.steam.SESSION_KEY", f"smt:test:session:{uuid.uuid4().hex}")
    service = SteamService(get_settings())
    await redis.delete(LOGIN_BLOCK_KEY, LOGIN_FAILURES_KEY)
    yield service
    await redis.delete(LOGIN_BLOCK_KEY, LOGIN_FAILURES_KEY)
    await service._redis.aclose()


@pytest.mark.asyncio
class TestLoginCooldown:
    async def test_no_cooldown_when_nothing_failed(self, steam_service):
        assert await steam_service._cooldown_remaining() is None

    async def test_a_failure_starts_a_cooldown(self, steam_service):
        cooldown = await steam_service._start_login_cooldown()

        assert cooldown > datetime.timedelta(0)
        assert await steam_service._cooldown_remaining() is not None

    async def test_the_cooldown_grows_with_repeated_failures(self, steam_service):
        first = await steam_service._start_login_cooldown()
        second = await steam_service._start_login_cooldown()

        assert second > first

    async def test_success_clears_it(self, steam_service):
        await steam_service._start_login_cooldown()
        await steam_service._clear_login_cooldown()

        assert await steam_service._cooldown_remaining() is None

    async def test_another_process_sees_the_same_cooldown(self, steam_service):
        """A fresh service stands in for a restarted worker."""
        await steam_service._start_login_cooldown()

        restarted = SteamService(get_settings())
        try:
            assert await restarted._cooldown_remaining() is not None
        finally:
            await restarted._redis.aclose()

    async def test_ensure_login_refuses_while_blocked(self, steam_service):
        await steam_service._start_login_cooldown()

        with pytest.raises(SteamLoginUnavailable, match="cooldown"):
            await steam_service._ensure_login()

    async def test_a_live_session_is_not_blocked_by_someone_elses_cooldown(self, steam_service):
        """The worker keeps trading while the web app backs off from a failed login."""
        steam_service._last_check = datetime.datetime.now(datetime.UTC)
        await steam_service._start_login_cooldown()

        await steam_service._ensure_login()


@pytest.mark.asyncio
class TestStandingBackFromSteam:
    """A refusal must slow the whole system down, not just the caller that hit it."""

    async def test_a_refusal_pauses_that_endpoint(self, steam_service, redis):
        await steam_service._stand_back("market")
        try:
            with pytest.raises(SteamThrottled, match="market"):
                await steam_service._take_a_slot("market")
        finally:
            await redis.delete(f"{COOLDOWN_KEY}market")

    async def test_other_endpoints_keep_working(self, steam_service, redis):
        await steam_service._stand_back("market")
        try:
            await steam_service._take_a_slot("orderbook")
        finally:
            await redis.delete(f"{COOLDOWN_KEY}market")

    async def test_another_process_stands_back_too(self, steam_service, redis):
        await steam_service._stand_back("pricehistory")
        restarted = SteamService(get_settings())
        try:
            with pytest.raises(SteamThrottled):
                await restarted._take_a_slot("pricehistory")
        finally:
            await redis.delete(f"{COOLDOWN_KEY}pricehistory")
            await restarted._redis.aclose()


@pytest.mark.asyncio
class TestBackingOffFurtherEachTime:
    """Steam keeps its own timer, so probing at a fixed rate can hold us in the penalty box."""

    async def clear(self, redis, bucket):
        await redis.delete(f"{COOLDOWN_KEY}{bucket}", f"{REFUSAL_COUNT_KEY}{bucket}")

    async def test_each_refusal_waits_longer(self, steam_service, redis):
        await self.clear(redis, "market")
        try:
            await steam_service._stand_back("market")
            first = await redis.ttl(f"{COOLDOWN_KEY}market")

            await steam_service._stand_back("market")
            second = await redis.ttl(f"{COOLDOWN_KEY}market")

            assert second > first
        finally:
            await self.clear(redis, "market")

    async def test_a_success_forgets_the_streak(self, steam_service, redis):
        await self.clear(redis, "market")
        try:
            await steam_service._stand_back("market")
            await steam_service._stand_back("market")
            await steam_service._worked_again("market")
            await redis.delete(f"{COOLDOWN_KEY}market")

            await steam_service._stand_back("market")

            assert await redis.ttl(f"{COOLDOWN_KEY}market") <= COOLDOWN_BASE
        finally:
            await self.clear(redis, "market")
