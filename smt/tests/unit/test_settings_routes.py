from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from smt.main import app
from smt.services.dependencies import get_pool_service, get_stats_refresh_service


@pytest.fixture
def refresh():
    service = AsyncMock()
    pool = AsyncMock()
    pool.list.return_value = [SimpleNamespace(market_hash_name="Air Head")]
    app.dependency_overrides[get_stats_refresh_service] = lambda: service
    app.dependency_overrides[get_pool_service] = lambda: pool
    yield service
    app.dependency_overrides.pop(get_stats_refresh_service, None)
    app.dependency_overrides.pop(get_pool_service, None)


async def current(client):
    return (await client.get("/api/v1/settings/")).json()


@pytest.mark.asyncio
class TestRejudgingThePool:
    async def test_a_rule_that_used_to_be_missed_now_rejudges(self, client, refresh):
        """Holding time, weekly volume and the return threshold all decide trades too."""
        settings = await current(client)

        await client.patch("/api/v1/settings/", json={"max_hold_hours": settings["max_hold_hours"] + 24})

        refresh.refresh_indicators.assert_awaited_once_with(["Air Head"])

    async def test_saving_the_whole_form_unchanged_costs_nothing(self, client, refresh):
        """The settings page sends every field on save; that alone must not hit Steam once per pool item."""
        settings = await current(client)
        form = {k: v for k, v in settings.items() if k not in ("id", "updated_at")}

        await client.patch("/api/v1/settings/", json=form)

        refresh.refresh_indicators.assert_not_awaited()

    async def test_a_setting_outside_the_judgement_does_not_rejudge(self, client, refresh):
        settings = await current(client)

        await client.patch("/api/v1/settings/", json={"emergency_stop": not settings["emergency_stop"]})

        refresh.refresh_indicators.assert_not_awaited()
