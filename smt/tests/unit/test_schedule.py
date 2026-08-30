import time

import pytest

from smt.worker.schedule import due


class FakeRedis:
    def __init__(self, values=None):
        self.values = values or {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value):
        self.values[key] = value


@pytest.mark.asyncio
class TestDue:
    async def test_runs_when_nothing_was_recorded(self):
        redis = FakeRedis()

        assert await due(redis, "prices", 30) is True

    async def test_remembers_the_run(self):
        redis = FakeRedis()

        await due(redis, "prices", 30)

        assert "smt:last_run:prices" in redis.values

    async def test_does_not_run_again_inside_the_interval(self):
        redis = FakeRedis({"smt:last_run:prices": time.time() - 60})

        assert await due(redis, "prices", 30) is False

    async def test_runs_once_the_interval_has_passed(self):
        redis = FakeRedis({"smt:last_run:prices": time.time() - 31 * 60})

        assert await due(redis, "prices", 30) is True

    async def test_a_zero_interval_always_runs(self):
        redis = FakeRedis({"smt:last_run:prices": time.time()})

        assert await due(redis, "prices", 0) is True

    async def test_jobs_are_tracked_separately(self):
        redis = FakeRedis({"smt:last_run:prices": time.time()})

        assert await due(redis, "prices", 30) is False
        assert await due(redis, "indicators", 30) is True
