from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from smt.api.v1.routes import steam as steam_route
from smt.main import app
from smt.services.dependencies import get_steam_service


@pytest.fixture(autouse=True)
def clean_cache():
    steam_route._cached = None
    steam_route._failed_at = None
    yield
    app.dependency_overrides.pop(get_steam_service, None)
    steam_route._cached = None
    steam_route._failed_at = None


@pytest.fixture
def steam():
    service = AsyncMock()
    app.dependency_overrides[get_steam_service] = lambda: service
    return service


@pytest.mark.asyncio
class TestWalletBalanceCache:
    async def test_a_success_is_reused(self, client, steam):
        steam.get_wallet_balance.return_value = Decimal("7.54")

        first = await client.get("/api/v1/steam/wallet")
        second = await client.get("/api/v1/steam/wallet")

        assert first.json()["balance"] == "7.54"
        assert second.json()["cached"] is True
        assert steam.get_wallet_balance.await_count == 1

    async def test_a_failure_is_remembered_too(self, client, steam):
        """Steam meters that page, so retrying on every page load makes throttling worse."""
        steam.get_wallet_balance.side_effect = Exception("Unable to get wallet balance string match")

        for _ in range(5):
            response = await client.get("/api/v1/steam/wallet")
            assert response.json()["stale"] is True

        assert steam.get_wallet_balance.await_count == 1

    async def test_the_last_known_balance_survives_a_failure(self, client, steam):
        steam.get_wallet_balance.return_value = Decimal("7.54")
        await client.get("/api/v1/steam/wallet")

        steam_route._cached = (steam_route._cached[0] - steam_route.BALANCE_TTL_SECONDS - 1, Decimal("7.54"))
        steam.get_wallet_balance.side_effect = Exception("throttled")

        response = await client.get("/api/v1/steam/wallet")

        assert response.json()["balance"] == "7.54"
        assert response.json()["stale"] is True
