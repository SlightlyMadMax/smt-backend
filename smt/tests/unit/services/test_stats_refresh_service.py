from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from steampy.exceptions import TooManyRequests

from smt.exceptions import OrderBookUnavailable
from smt.schemas.action_log import ActionKind
from smt.services import steam as steam_module
from smt.services.market_analytics import SellChoice
from smt.services.stats_refresh import StatsRefreshService
from smt.services.steam import ACCOUNT_CURRENCY, SteamService


def order_book_payload(currency=int(ACCOUNT_CURRENCY), min_sell=682, max_buy=668):
    return {
        "data": {
            "success": True,
            "data": {
                "eCurrency": currency,
                "amtMinSellOrder": min_sell,
                "amtMaxBuyOrder": max_buy,
                "cSellOrders": 38170,
                "cBuyOrders": 528386,
                "rgCompactSellOrders": [min_sell, 443],
                "rgCompactBuyOrders": [max_buy, 2228],
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

    async def get(self, url, params=None, cookies=None):
        self.calls.append((url, params, cookies))
        return self._response


@pytest.fixture
def steam_service():
    with patch.object(SteamService, "__init__", lambda self, settings=None: None):
        service = SteamService()
    service.client = SimpleNamespace(_session=SimpleNamespace(cookies=SimpleNamespace(get_dict=lambda domain: {})))
    service._ensure_login = AsyncMock()
    service._take_a_slot = AsyncMock()
    service._worked_again = AsyncMock()
    return service


@pytest.mark.asyncio
class TestGetOrderBook:
    async def test_converts_minor_units_to_currency(self, steam_service):
        fake = FakeAsyncClient(FakeResponse(order_book_payload()))
        with patch.object(steam_module.httpx, "AsyncClient", fake):
            book = await steam_service.get_order_book("Secret Saxton", "440")

        assert book["lowest_sell_order"] == Decimal("6.82")
        assert book["highest_buy_order"] == Decimal("6.68")
        assert book["sell_order_count"] == 38170
        assert book["buy_order_count"] == 528386

    async def test_wraps_transport_errors(self, steam_service):
        class Failing(FakeAsyncClient):
            async def get(self, url, params=None, cookies=None):
                raise httpx.ConnectError("boom")

        with patch.object(steam_module.httpx, "AsyncClient", Failing(None)):
            with pytest.raises(OrderBookUnavailable, match="Could not reach"):
                await steam_service.get_order_book("Secret Saxton", "440")

    async def test_rejects_a_foreign_currency(self, steam_service):
        fake = FakeAsyncClient(FakeResponse(order_book_payload(currency=3, min_sell=8, max_buy=6)))
        with patch.object(steam_module.httpx, "AsyncClient", fake):
            with pytest.raises(OrderBookUnavailable, match="currency 3"):
                await steam_service.get_order_book("Secret Saxton", "440")

    async def test_sends_session_cookies(self, steam_service):
        steam_service.client._session.cookies.get_dict = lambda domain: {"steamLoginSecure": "token"}
        fake = FakeAsyncClient(FakeResponse(order_book_payload()))
        with patch.object(steam_module.httpx, "AsyncClient", fake):
            await steam_service.get_order_book("Secret Saxton", "440")

        assert fake.calls[0][2] == {"steamLoginSecure": "token"}

    async def test_sends_appid_and_name_as_qp(self, steam_service):
        fake = FakeAsyncClient(FakeResponse(order_book_payload()))
        with patch.object(steam_module.httpx, "AsyncClient", fake):
            await steam_service.get_order_book("Mann Co. Supply Crate Key", "440")

        _, params, _ = fake.calls[0]
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
            "lowest_sell_order": Decimal("6.82"),
            "highest_buy_order": Decimal("6.68"),
            "sell_order_count": 1,
            "buy_order_count": 2,
        }

        await refresh_service.refresh_current_stats("item")

        payload = refresh_service.pool_service.update.await_args.args[1]
        assert payload.current_median_price == Decimal("195.07")
        assert payload.current_volume24h == 58919
        assert payload.current_lowest_price == Decimal("6.82")
        assert payload.current_highest_buy_order == Decimal("6.68")

    async def test_still_stores_history_stats_when_the_order_book_fails(self, refresh_service):
        refresh_service.steam.get_order_book.side_effect = OrderBookUnavailable("gone")

        await refresh_service.refresh_current_stats("item")

        payload = refresh_service.pool_service.update.await_args.args[1]
        assert payload.current_median_price == Decimal("195.07")
        assert payload.current_volume24h == 58919
        assert "current_lowest_price" not in payload.model_dump(exclude_unset=True)

    async def test_survives_a_network_error(self, refresh_service):
        refresh_service.steam.get_order_book.side_effect = OrderBookUnavailable("unreachable")

        await refresh_service.refresh_current_stats("item")

        refresh_service.pool_service.update.assert_awaited_once()


def history_record(price: str, volume: int = 10):
    return SimpleNamespace(price=Decimal(price), volume=volume, recorded_at=None)


@pytest.fixture
def indicator_service(refresh_service):
    refresh_service.settings_service.get_settings.return_value = SimpleNamespace(
        analysis_window_days=7, sell_percentile=90
    )
    refresh_service.analytics_service.filter_price_outliers = lambda records: records
    refresh_service.analytics_service.compute_buy_target.return_value = Decimal("6.21")
    refresh_service.analytics_service.choose_sell_price = lambda **kwargs: SellChoice(
        percentile=82,
        price=Decimal("8.01"),
        profit=Decimal("0.77"),
        round_trips=8,
        median_hold_hours=Decimal("12.0"),
        queue_ahead=14,
        days_to_clear=Decimal("0.5"),
        feasible_round_trips=6,
    )
    refresh_service.analytics_service.compute_volume_weighted_volatility.return_value = Decimal("0.095")
    refresh_service.analytics_service.decide_trade_flag.return_value = (True, "")
    refresh_service.analytics_service.project_return_on_capital = lambda profit, trips, buy, days: Decimal("120.0")
    refresh_service.price_history_service.list.return_value = [history_record("6.90"), history_record("6.95")]
    refresh_service.steam.get_order_book.return_value = {"sell_levels": [], "buy_levels": []}
    return refresh_service


@pytest.mark.asyncio
class TestIndicatorDriftGuard:
    async def test_keeps_the_flag_when_history_matches_the_market(self, indicator_service):
        indicator_service.pool_service.get_many.return_value = [
            SimpleNamespace(market_hash_name="item", current_volume24h=1000, current_lowest_price=Decimal("6.82"))
        ]
        indicator_service.analytics_service.history_describes_current_market = lambda records, price: True

        await indicator_service.refresh_indicators(["item"])

        payload = indicator_service.pool_service.update.await_args.args[1]
        assert payload.use_for_trading is True

    async def test_clears_the_flag_when_history_is_far_from_the_market(self, indicator_service):
        indicator_service.pool_service.get_many.return_value = [
            SimpleNamespace(market_hash_name="item", current_volume24h=1000, current_lowest_price=Decimal("5.18"))
        ]
        indicator_service.analytics_service.history_describes_current_market = lambda records, price: False

        await indicator_service.refresh_indicators(["item"])

        payload = indicator_service.pool_service.update.await_args.args[1]
        assert payload.use_for_trading is False


@pytest.mark.asyncio
class TestTheAskingPriceThePoolStores:
    @staticmethod
    def item():
        return SimpleNamespace(
            market_hash_name="item", app_id="440", current_volume24h=1000, current_lowest_price=Decimal("6.82")
        )

    async def test_the_chosen_price_and_its_reasoning_are_kept(self, indicator_service):
        indicator_service.pool_service.get_many.return_value = [self.item()]
        indicator_service.analytics_service.history_describes_current_market = lambda records, price: True

        await indicator_service.refresh_indicators(["item"])

        payload = indicator_service.pool_service.update.await_args.args[1]
        assert payload.optimal_sell_price == Decimal("8.01")
        assert payload.sell_percentile_used == 82
        assert payload.queue_ahead == 14
        assert payload.days_to_clear == Decimal("0.5")
        assert payload.feasible_round_trips == 6

    async def test_the_return_is_computed_from_the_trips_the_queue_allows(self, indicator_service):
        """Eight trips in the history, six the queue leaves room for; the return follows the six."""
        seen = {}

        def remember(profit, trips, buy, days):
            seen["trips"] = trips
            return Decimal("120.0")

        indicator_service.analytics_service.project_return_on_capital = remember
        indicator_service.pool_service.get_many.return_value = [self.item()]
        indicator_service.analytics_service.history_describes_current_market = lambda records, price: True

        await indicator_service.refresh_indicators(["item"])

        assert seen["trips"] == 6

    async def test_an_unreadable_book_does_not_stop_the_refresh(self, indicator_service):
        indicator_service.steam.get_order_book.side_effect = RuntimeError("429")
        indicator_service.pool_service.get_many.return_value = [self.item()]
        indicator_service.analytics_service.history_describes_current_market = lambda records, price: True

        await indicator_service.refresh_indicators(["item"])

        indicator_service.pool_service.update.assert_awaited()


@pytest.mark.asyncio
class TestPriceHistoryThrottling:
    """Steam meters price history separately, and one refusal must not cost the whole batch."""

    @staticmethod
    def service_with(steam, action_log=None):
        return StatsRefreshService(
            price_history_service=AsyncMock(),
            pool_service=AsyncMock(),
            steam_service=steam,
            analytics_service=AsyncMock(),
            settings_service=AsyncMock(),
            action_log=action_log,
        )

    async def test_a_throttled_item_does_not_stop_the_others(self):
        steam = AsyncMock()
        steam.get_price_history.side_effect = [TooManyRequests("slow down"), []]
        service = self.service_with(steam)
        service.settings_service.get_settings.return_value = SimpleNamespace(price_history_days=30)
        service.pool_service.get_by_market_hash_name.return_value = SimpleNamespace(app_id="440", context_id="2")

        await service.refresh_price_history(["First", "Second"])

        assert steam.get_price_history.await_count == 2

    async def test_being_throttled_is_written_to_the_journal(self):
        steam = AsyncMock()
        steam.get_price_history.side_effect = TooManyRequests("slow down")
        action_log = AsyncMock()
        service = self.service_with(steam, action_log)
        service.settings_service.get_settings.return_value = SimpleNamespace(price_history_days=30)
        service.pool_service.get_by_market_hash_name.return_value = SimpleNamespace(app_id="440", context_id="2")

        await service.refresh_price_history(["First"])

        action_log.record.assert_awaited_once()
        assert action_log.record.await_args.args[0] == ActionKind.STEAM_THROTTLED
