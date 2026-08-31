"""These run against the Redis the application actually uses."""

import asyncio
import datetime
import time
import uuid

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from smt.core.config import get_settings
from smt.exceptions import SteamLoginUnavailable
from smt.services.steam import LOGIN_BLOCK_KEY, LOGIN_FAILURES_KEY, SteamService
from smt.utils.rate_limit import RedisRateLimiter


@pytest_asyncio.fixture
async def redis():
    settings = get_settings()
    client = Redis(host=settings.REDIS_HOST, port=int(settings.REDIS_PORT))
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
async def steam_service(redis):
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
