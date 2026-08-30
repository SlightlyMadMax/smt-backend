from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from smt.exceptions import OrderBookUnavailable
from smt.services import steam as steam_module
from smt.services.stats_refresh import StatsRefreshService
from smt.services.steam import SteamService


ORDER_BOOK_OK = {
    "data": {
        "success": True,
        "data": {
            "amtMinSellOrder": 196,
            "amtMaxBuyOrder": 195,
            "cSellOrders": 38170,
            "cBuyOrders": 528386,
            "rgCompactSellOrders": [196, 443, 197, 749],
            "rgCompactBuyOrders": [195, 2228, 193, 18883],
        },
    }
}


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=None)

    def json(self):
        return self._payload


class FakeAsyncClient:
    def __init__(self, response):
        self._response = response
        self.calls = []

    def __call__(self, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, url, params=None):
        self.calls.append((url, params))
        return self._response


@pytest.fixture
def steam_service():
    with patch.object(SteamService, "__init__", lambda self, settings=None: None):
        return SteamService()


@pytest.mark.asyncio
class TestGetOrderBook:
    async def test_parses_the_order_book(self, steam_service):
        fake = FakeAsyncClient(FakeResponse(ORDER_BOOK_OK))
        with patch.object(steam_module.httpx, "AsyncClient", fake):
            book = await steam_service.get_order_book("Mann Co. Supply Crate Key", "440")

        assert book["lowest_sell_order"] == Decimal("196")
        assert book["highest_buy_order"] == Decimal("195")
        assert book["sell_order_count"] == 38170
        assert book["buy_order_count"] == 528386

    async def test_sends_appid_and_name_as_qp(self, steam_service):
        fake = FakeAsyncClient(FakeResponse(ORDER_BOOK_OK))
        with patch.object(steam_module.httpx, "AsyncClient", fake):
            await steam_service.get_order_book("Mann Co. Supply Crate Key", "440")

        _, params = fake.calls[0]
        assert params["q"] == "Load"
        assert params["qp"] == '[440,"Mann Co. Supply Crate Key"]'

    async def test_raises_when_steam_reports_no_order_book(self, steam_service):
        fake = FakeAsyncClient(FakeResponse({"data": {"success": False}}))
        with patch.object(steam_module.httpx, "AsyncClient", fake):
            with pytest.raises(OrderBookUnavailable):
                await steam_service.get_order_book("Not A Real Item", "440")


@pytest.fixture
def refresh_service():
    service = StatsRefreshService(
        price_history_service=AsyncMock(),
        pool_service=AsyncMock(),
        steam_service=AsyncMock(),
        analytics_service=AsyncMock(),
        settings_service=AsyncMock(),
    )
    service.pool_service.get_by_market_hash_name.return_value = SimpleNamespace(
        market_hash_name="item", app_id="440", context_id="2"
    )
    service.price_history_service.list.return_value = []
    service.analytics_service.compute_recent_stats.return_value = (Decimal("195.07"), 58919)
    return service


@pytest.mark.asyncio
class TestRefreshCurrentStats:
    async def test_writes_all_four_fields(self, refresh_service):
        refresh_service.steam.get_order_book.return_value = {
            "lowest_sell_order": Decimal("196"),
            "highest_buy_order": Decimal("195"),
            "sell_order_count": 1,
            "buy_order_count": 2,
        }

        await refresh_service.refresh_current_stats("item")

        payload = refresh_service.pool_service.update.await_args.args[1]
        assert payload.current_median_price == Decimal("195.07")
        assert payload.current_volume24h == 58919
        assert payload.current_lowest_price == Decimal("196")
        assert payload.current_highest_buy_order == Decimal("195")

    async def test_still_stores_history_stats_when_the_order_book_fails(self, refresh_service):
        refresh_service.steam.get_order_book.side_effect = OrderBookUnavailable("gone")

        await refresh_service.refresh_current_stats("item")

        payload = refresh_service.pool_service.update.await_args.args[1]
        assert payload.current_median_price == Decimal("195.07")
        assert payload.current_volume24h == 58919
        assert "current_lowest_price" not in payload.model_dump(exclude_unset=True)

    async def test_survives_a_network_error(self, refresh_service):
        refresh_service.steam.get_order_book.side_effect = httpx.ConnectError("boom")

        await refresh_service.refresh_current_stats("item")

        refresh_service.pool_service.update.assert_awaited_once()
