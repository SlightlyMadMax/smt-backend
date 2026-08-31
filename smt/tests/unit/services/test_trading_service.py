from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from smt.exceptions import OrderBookUnavailable
from smt.schemas.position import PositionStatus
from smt.services.trading import CANCEL_GRACE_PERIOD, TradingService


ITEM_HASH = "AK-47 | Redline (Field-Tested)"
GAME_KEY = ("730", "2")
NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def make_position(position_id: int, status: PositionStatus, asset_id=None, sell_order_id=None, created_at=None):
    return SimpleNamespace(
        id=position_id,
        buy_order_id=f"BUY-{position_id}",
        pool_item_hash=ITEM_HASH,
        pool_item=SimpleNamespace(app_id="730", context_id="2"),
        asset_id=asset_id,
        sell_order_id=sell_order_id,
        buy_price=Decimal("10.00"),
        sell_price=Decimal("15.00"),
        status=status,
        created_at=created_at or (NOW - CANCEL_GRACE_PERIOD - timedelta(minutes=1)),
    )


def make_asset(asset_id: str, first_seen_at: datetime):
    return SimpleNamespace(id=asset_id, market_hash_name=ITEM_HASH, first_seen_at=first_seen_at)


def make_listing(listing_id: str, asset_id: str, need_confirmation: bool = False):
    listing = {"listing_id": listing_id, "description": {"id": asset_id}}
    if need_confirmation:
        listing["need_confirmation"] = True
    return listing


@pytest.fixture
def position_service():
    service = AsyncMock()
    service.list_by_status.return_value = []
    service.list.return_value = []
    return service


def make_settings(
    max_concurrent_trades=10,
    max_investment_per_item=Decimal("50.00"),
    max_daily_loss=Decimal("100.00"),
    cooldown_after_loss_hours=24,
):
    return SimpleNamespace(
        max_concurrent_trades=max_concurrent_trades,
        max_investment_per_item=max_investment_per_item,
        max_daily_loss=max_daily_loss,
        cooldown_after_loss_hours=cooldown_after_loss_hours,
        emergency_stop=False,
        cancel_untracked_orders=False,
    )


@pytest.fixture
def trading_service(position_service):
    service = TradingService(
        steam_service=AsyncMock(),
        inventory_service=AsyncMock(),
        position_service=position_service,
        pool_item_service=AsyncMock(),
        settings_service=AsyncMock(),
        action_log=AsyncMock(),
    )
    service.settings_service.get_settings.return_value = make_settings()
    service.steam_service.get_wallet_balance.return_value = Decimal("1000.00")
    position_service.realized_profit_since.return_value = Decimal("0")
    position_service.last_loss_at.return_value = None
    return service


@pytest.mark.asyncio
class TestResolvePendingListings:
    async def test_matches_listing_by_asset_id(self, trading_service, position_service):
        position_service.list_by_status.return_value = [
            make_position(1, PositionStatus.LISTING_PENDING, asset_id="ASSET-1")
        ]

        await trading_service._resolve_pending_listings([make_listing("LISTING-9", "ASSET-1")])

        position_service.mark_as_listed.assert_awaited_once_with(position_id=1, sell_order_id="LISTING-9")

    async def test_ignores_listing_of_a_different_asset(self, trading_service, position_service):
        position_service.list_by_status.return_value = [
            make_position(1, PositionStatus.LISTING_PENDING, asset_id="ASSET-1")
        ]

        await trading_service._resolve_pending_listings([make_listing("LISTING-9", "ASSET-2")])

        position_service.mark_as_listed.assert_not_awaited()

    async def test_skips_listings_awaiting_confirmation(self, trading_service, position_service):
        position_service.list_by_status.return_value = [
            make_position(1, PositionStatus.LISTING_PENDING, asset_id="ASSET-1")
        ]

        await trading_service._resolve_pending_listings([make_listing("LISTING-9", "ASSET-1", need_confirmation=True)])

        position_service.mark_as_listed.assert_not_awaited()

    async def test_no_listings_leaves_position_pending(self, trading_service, position_service):
        position_service.list_by_status.return_value = [
            make_position(1, PositionStatus.LISTING_PENDING, asset_id="ASSET-1")
        ]

        await trading_service._resolve_pending_listings([])

        position_service.mark_as_listed.assert_not_awaited()


@pytest.mark.asyncio
class TestSyncListedToClosed:
    async def test_keeps_position_while_listing_is_active(self, trading_service, position_service):
        position_service.list_by_status.return_value = [
            make_position(1, PositionStatus.LISTED, asset_id="ASSET-1", sell_order_id="LISTING-9")
        ]

        await trading_service._sync_listed_to_closed([make_listing("LISTING-9", "ASSET-1")])

        position_service.close.assert_not_awaited()

    async def test_closes_position_when_listing_is_gone(self, trading_service, position_service):
        position_service.list_by_status.return_value = [
            make_position(1, PositionStatus.LISTED, asset_id="ASSET-1", sell_order_id="LISTING-9")
        ]

        await trading_service._sync_listed_to_closed([])

        position_service.close.assert_awaited_once_with(position_id=1)

    async def test_skips_position_without_listing_id(self, trading_service, position_service):
        position_service.list_by_status.return_value = [
            make_position(1, PositionStatus.LISTED, asset_id="ASSET-1", sell_order_id=None)
        ]

        await trading_service._sync_listed_to_closed([])

        position_service.close.assert_not_awaited()


@pytest.mark.asyncio
class TestListBoughtPositions:
    async def test_moves_position_to_listing_pending(self, trading_service, position_service):
        position_service.list_by_status.return_value = [make_position(1, PositionStatus.BOUGHT, asset_id="ASSET-1")]

        await trading_service._list_bought_positions()

        trading_service.steam_service.create_sell_order.assert_awaited_once()
        position_service.mark_as_listing_pending.assert_awaited_once_with(position_id=1)
        position_service.mark_as_listed.assert_not_awaited()


@pytest.mark.asyncio
class TestSyncOpenToBought:
    async def test_claims_asset_that_arrived_after_the_position_was_opened(self, trading_service, position_service):
        position = make_position(1, PositionStatus.OPEN)
        position_service.list_by_status.return_value = [position]
        position_service.list.return_value = []
        assets = {GAME_KEY: {ITEM_HASH: [make_asset("NEW-1", position.created_at + timedelta(minutes=1))]}}

        await trading_service._sync_open_to_bought(assets, buy_orders=[])

        position_service.mark_as_bought.assert_awaited_once_with(position_id=1, asset_id="NEW-1")
        position_service.mark_as_cancelled.assert_not_awaited()

    async def test_never_claims_an_asset_owned_before_the_position(self, trading_service, position_service):
        position = make_position(1, PositionStatus.OPEN)
        position_service.list_by_status.return_value = [position]
        position_service.list.return_value = []
        assets = {GAME_KEY: {ITEM_HASH: [make_asset("OWNED", position.created_at - timedelta(days=365))]}}

        await trading_service._sync_open_to_bought(assets, buy_orders=[])

        position_service.mark_as_bought.assert_not_awaited()
        position_service.mark_as_cancelled.assert_awaited_once_with(position_id=1)

    async def test_leaves_position_alone_while_buy_order_is_active(self, trading_service, position_service):
        position_service.list_by_status.return_value = [make_position(1, PositionStatus.OPEN)]
        position_service.list.return_value = []

        await trading_service._sync_open_to_bought({}, buy_orders=[{"order_id": "BUY-1"}])

        position_service.mark_as_bought.assert_not_awaited()
        position_service.mark_as_cancelled.assert_not_awaited()

    async def test_does_not_cancel_within_the_grace_period(self, trading_service, position_service):
        fresh = make_position(1, PositionStatus.OPEN, created_at=datetime.now(timezone.utc))
        position_service.list_by_status.return_value = [fresh]
        position_service.list.return_value = []

        await trading_service._sync_open_to_bought({}, buy_orders=[])

        position_service.mark_as_cancelled.assert_not_awaited()

    async def test_does_not_claim_an_asset_taken_by_another_position(self, trading_service, position_service):
        position = make_position(2, PositionStatus.OPEN)
        position_service.list_by_status.return_value = [position]
        position_service.list.return_value = [make_position(1, PositionStatus.BOUGHT, asset_id="NEW-1")]
        assets = {GAME_KEY: {ITEM_HASH: [make_asset("NEW-1", position.created_at + timedelta(minutes=1))]}}

        await trading_service._sync_open_to_bought(assets, buy_orders=[])

        position_service.mark_as_bought.assert_not_awaited()
        position_service.mark_as_cancelled.assert_awaited_once_with(position_id=2)


def make_pool_item(buy=Decimal("6.00"), sell=Decimal("7.77"), max_listed=1):
    return SimpleNamespace(
        market_hash_name=ITEM_HASH,
        app_id="440",
        context_id="2",
        max_listed=max_listed,
        effective_buy_price=buy,
        effective_sell_price=sell,
    )


def make_book(lowest_ask, highest_bid=Decimal("6.68")):
    return {
        "lowest_sell_order": lowest_ask,
        "highest_buy_order": highest_bid,
        "sell_order_count": 10,
        "buy_order_count": 20,
    }


@pytest.mark.asyncio
class TestOpenNewPositions:
    async def test_places_an_order_below_the_cheapest_listing(self, trading_service, position_service):
        trading_service.pool_item_service.list_marked_for_trading.return_value = [make_pool_item(buy=Decimal("6.00"))]
        position_service.list_active.return_value = []
        trading_service.steam_service.get_order_book.return_value = make_book(Decimal("6.82"))
        trading_service.steam_service.create_buy_order.return_value = "BUY-9"

        await trading_service._open_new_positions()

        trading_service.steam_service.create_buy_order.assert_awaited_once()
        assert trading_service.steam_service.create_buy_order.await_args.kwargs["price"] == Decimal("6.00")
        position_service.add.assert_awaited_once()

    async def test_skips_when_the_order_would_fill_at_market(self, trading_service, position_service):
        trading_service.pool_item_service.list_marked_for_trading.return_value = [make_pool_item(buy=Decimal("6.91"))]
        position_service.list_active.return_value = []
        trading_service.steam_service.get_order_book.return_value = make_book(Decimal("6.82"))

        await trading_service._open_new_positions()

        trading_service.steam_service.create_buy_order.assert_not_awaited()
        position_service.add.assert_not_awaited()

    async def test_skips_when_the_price_equals_the_cheapest_listing(self, trading_service, position_service):
        trading_service.pool_item_service.list_marked_for_trading.return_value = [make_pool_item(buy=Decimal("6.82"))]
        position_service.list_active.return_value = []
        trading_service.steam_service.get_order_book.return_value = make_book(Decimal("6.82"))

        await trading_service._open_new_positions()

        trading_service.steam_service.create_buy_order.assert_not_awaited()

    async def test_skips_when_the_order_book_is_unavailable(self, trading_service, position_service):
        trading_service.pool_item_service.list_marked_for_trading.return_value = [make_pool_item()]
        position_service.list_active.return_value = []
        trading_service.steam_service.get_order_book.side_effect = OrderBookUnavailable("nope")

        await trading_service._open_new_positions()

        trading_service.steam_service.create_buy_order.assert_not_awaited()

    async def test_skips_when_there_is_no_buy_price(self, trading_service, position_service):
        trading_service.pool_item_service.list_marked_for_trading.return_value = [make_pool_item(buy=None)]
        position_service.list_active.return_value = []

        await trading_service._open_new_positions()

        trading_service.steam_service.get_order_book.assert_not_awaited()
        trading_service.steam_service.create_buy_order.assert_not_awaited()

    async def test_reads_the_order_book_once_per_item(self, trading_service, position_service):
        trading_service.pool_item_service.list_marked_for_trading.return_value = [
            make_pool_item(buy=Decimal("6.00"), max_listed=3)
        ]
        position_service.list_active.return_value = []
        trading_service.steam_service.get_order_book.return_value = make_book(Decimal("6.82"))
        trading_service.steam_service.create_buy_order.return_value = "BUY-9"

        await trading_service._open_new_positions()

        assert trading_service.steam_service.get_order_book.await_count == 1
        assert trading_service.steam_service.create_buy_order.await_count == 3


@pytest.mark.asyncio
class TestReconcileOrders:
    async def test_ignores_orders_owned_by_an_active_position(self, trading_service, position_service):
        position_service.list_active.return_value = [make_position(1, PositionStatus.OPEN)]

        await trading_service._reconcile_orders([{"order_id": "BUY-1"}], [], cancel=False)

        trading_service.steam_service.cancel_buy_order.assert_not_awaited()

    async def test_reports_an_order_no_active_position_owns(self, trading_service, position_service):
        position_service.list_active.return_value = []

        await trading_service._reconcile_orders([{"order_id": "BUY-99"}], [], cancel=False)

        trading_service.steam_service.cancel_buy_order.assert_not_awaited()

    async def test_cancels_untracked_orders_when_asked(self, trading_service, position_service):
        position_service.list_active.return_value = []

        await trading_service._reconcile_orders([{"order_id": "BUY-99"}], [], cancel=True)

        trading_service.steam_service.cancel_buy_order.assert_awaited_once_with("BUY-99")

    async def test_a_cancelled_position_no_longer_shields_its_order(self, trading_service, position_service):
        position_service.list_active.return_value = []

        await trading_service._reconcile_orders([{"order_id": "BUY-1"}], [], cancel=True)

        trading_service.steam_service.cancel_buy_order.assert_awaited_once_with("BUY-1")

    async def test_listing_matched_by_asset_is_left_alone(self, trading_service, position_service):
        position_service.list_active.return_value = [
            make_position(1, PositionStatus.LISTING_PENDING, asset_id="ASSET-1")
        ]

        await trading_service._reconcile_orders([], [make_listing("LISTING-9", "ASSET-1")], cancel=True)

        trading_service.steam_service.cancel_sell_listing.assert_not_awaited()

    async def test_listing_matched_by_id_is_left_alone(self, trading_service, position_service):
        position_service.list_active.return_value = [
            make_position(1, PositionStatus.LISTED, asset_id="OTHER", sell_order_id="LISTING-9")
        ]

        await trading_service._reconcile_orders([], [make_listing("LISTING-9", "ASSET-1")], cancel=True)

        trading_service.steam_service.cancel_sell_listing.assert_not_awaited()

    async def test_cancels_an_untracked_listing_when_asked(self, trading_service, position_service):
        position_service.list_active.return_value = []

        await trading_service._reconcile_orders([], [make_listing("LISTING-9", "ASSET-1")], cancel=True)

        trading_service.steam_service.cancel_sell_listing.assert_awaited_once_with("LISTING-9")


@pytest.mark.asyncio
class TestOpenNewPositionsLimits:
    async def test_stops_when_all_trade_slots_are_taken(self, trading_service, position_service):
        trading_service.settings_service.get_settings.return_value = make_settings(max_concurrent_trades=2)
        position_service.list_active.return_value = [
            make_position(1, PositionStatus.OPEN),
            make_position(2, PositionStatus.LISTED),
        ]
        trading_service.pool_item_service.list_marked_for_trading.return_value = [make_pool_item()]

        await trading_service._open_new_positions()

        trading_service.steam_service.get_wallet_balance.assert_not_awaited()
        trading_service.steam_service.create_buy_order.assert_not_awaited()

    async def test_free_slots_cap_how_many_orders_are_placed(self, trading_service, position_service):
        trading_service.settings_service.get_settings.return_value = make_settings(max_concurrent_trades=2)
        position_service.list_active.return_value = [make_position(1, PositionStatus.OPEN)]
        trading_service.pool_item_service.list_marked_for_trading.return_value = [
            make_pool_item(buy=Decimal("6.00"), max_listed=5)
        ]
        trading_service.steam_service.get_order_book.return_value = make_book(Decimal("6.82"))
        trading_service.steam_service.create_buy_order.return_value = "BUY-9"

        await trading_service._open_new_positions()

        assert trading_service.steam_service.create_buy_order.await_count == 1

    async def test_a_single_order_may_not_exceed_the_balance(self, trading_service, position_service):
        position_service.list_active.return_value = []
        trading_service.steam_service.get_wallet_balance.return_value = Decimal("5.00")
        trading_service.pool_item_service.list_marked_for_trading.return_value = [
            make_pool_item(buy=Decimal("6.00"), max_listed=5)
        ]
        trading_service.steam_service.get_order_book.return_value = make_book(Decimal("6.82"))

        await trading_service._open_new_positions()

        trading_service.steam_service.create_buy_order.assert_not_awaited()

    async def test_open_orders_may_total_ten_times_the_balance(self, trading_service, position_service):
        trading_service.settings_service.get_settings.return_value = make_settings(max_concurrent_trades=50)
        position_service.list_active.return_value = []
        trading_service.steam_service.get_wallet_balance.return_value = Decimal("2.00")
        trading_service.pool_item_service.list_marked_for_trading.return_value = [
            make_pool_item(buy=Decimal("1.50"), max_listed=20)
        ]
        trading_service.steam_service.get_order_book.return_value = make_book(Decimal("6.82"))
        trading_service.steam_service.create_buy_order.return_value = "BUY-9"

        await trading_service._open_new_positions()

        assert trading_service.steam_service.create_buy_order.await_count == 13

    async def test_existing_open_orders_eat_into_the_allowance(self, trading_service, position_service):
        held = make_position(1, PositionStatus.OPEN)
        held.buy_price = Decimal("18.00")
        position_service.list_active.return_value = [held]
        trading_service.steam_service.get_wallet_balance.return_value = Decimal("2.00")
        trading_service.pool_item_service.list_marked_for_trading.return_value = [
            make_pool_item(buy=Decimal("1.00"), max_listed=20)
        ]
        trading_service.steam_service.get_order_book.return_value = make_book(Decimal("6.82"))
        trading_service.steam_service.create_buy_order.return_value = "BUY-9"

        await trading_service._open_new_positions()

        assert trading_service.steam_service.create_buy_order.await_count == 2

    async def test_filled_positions_do_not_count_towards_the_allowance(self, trading_service, position_service):
        held = make_position(1, PositionStatus.LISTED)
        held.buy_price = Decimal("18.00")
        held.pool_item_hash = "Some Other Item"
        position_service.list_active.return_value = [held]
        trading_service.steam_service.get_wallet_balance.return_value = Decimal("2.00")
        trading_service.pool_item_service.list_marked_for_trading.return_value = [
            make_pool_item(buy=Decimal("1.00"), max_listed=5)
        ]
        trading_service.steam_service.get_order_book.return_value = make_book(Decimal("6.82"))
        trading_service.steam_service.create_buy_order.return_value = "BUY-9"

        await trading_service._open_new_positions()

        assert trading_service.steam_service.create_buy_order.await_count == 5

    async def test_skips_everything_when_the_balance_is_unknown(self, trading_service, position_service):
        position_service.list_active.return_value = []
        trading_service.steam_service.get_wallet_balance.side_effect = RuntimeError("no session")
        trading_service.pool_item_service.list_marked_for_trading.return_value = [make_pool_item()]

        await trading_service._open_new_positions()

        trading_service.steam_service.create_buy_order.assert_not_awaited()

    async def test_respects_the_per_item_budget(self, trading_service, position_service):
        trading_service.settings_service.get_settings.return_value = make_settings(
            max_investment_per_item=Decimal("18.00")
        )
        position_service.list_active.return_value = []
        trading_service.pool_item_service.list_marked_for_trading.return_value = [
            make_pool_item(buy=Decimal("6.00"), max_listed=5)
        ]
        trading_service.steam_service.get_order_book.return_value = make_book(Decimal("6.82"))
        trading_service.steam_service.create_buy_order.return_value = "BUY-9"

        await trading_service._open_new_positions()

        assert trading_service.steam_service.create_buy_order.await_count == 3

    async def test_counts_money_already_committed_to_the_item(self, trading_service, position_service):
        trading_service.settings_service.get_settings.return_value = make_settings(
            max_investment_per_item=Decimal("18.00")
        )
        held = make_position(1, PositionStatus.OPEN)
        held.buy_price = Decimal("12.00")
        position_service.list_active.return_value = [held]
        trading_service.pool_item_service.list_marked_for_trading.return_value = [
            make_pool_item(buy=Decimal("6.00"), max_listed=5)
        ]
        trading_service.steam_service.get_order_book.return_value = make_book(Decimal("6.82"))
        trading_service.steam_service.create_buy_order.return_value = "BUY-9"

        await trading_service._open_new_positions()

        assert trading_service.steam_service.create_buy_order.await_count == 1

    async def test_skips_the_item_when_its_budget_is_already_spent(self, trading_service, position_service):
        trading_service.settings_service.get_settings.return_value = make_settings(
            max_investment_per_item=Decimal("10.00")
        )
        held = make_position(1, PositionStatus.OPEN)
        held.buy_price = Decimal("10.00")
        position_service.list_active.return_value = [held]
        trading_service.pool_item_service.list_marked_for_trading.return_value = [
            make_pool_item(buy=Decimal("6.00"), max_listed=5)
        ]

        await trading_service._open_new_positions()

        trading_service.steam_service.get_order_book.assert_not_awaited()
        trading_service.steam_service.create_buy_order.assert_not_awaited()


@pytest.mark.asyncio
class TestDailyLossLimit:
    async def test_trades_while_the_day_is_profitable(self, trading_service, position_service):
        position_service.realized_profit_since.return_value = Decimal("5.00")
        position_service.list_active.return_value = []
        trading_service.pool_item_service.list_marked_for_trading.return_value = [make_pool_item(buy=Decimal("6.00"))]
        trading_service.steam_service.get_order_book.return_value = make_book(Decimal("6.82"))
        trading_service.steam_service.create_buy_order.return_value = "BUY-9"

        await trading_service._open_new_positions()

        trading_service.steam_service.create_buy_order.assert_awaited_once()

    async def test_stops_once_the_daily_loss_limit_is_passed(self, trading_service, position_service):
        trading_service.settings_service.get_settings.return_value = make_settings(max_daily_loss=Decimal("10.00"))
        position_service.realized_profit_since.return_value = Decimal("-10.01")
        position_service.list_active.return_value = []
        trading_service.pool_item_service.list_marked_for_trading.return_value = [make_pool_item()]

        await trading_service._open_new_positions()

        trading_service.steam_service.get_wallet_balance.assert_not_awaited()
        trading_service.steam_service.create_buy_order.assert_not_awaited()

    async def test_a_loss_inside_the_limit_still_trades(self, trading_service, position_service):
        trading_service.settings_service.get_settings.return_value = make_settings(max_daily_loss=Decimal("10.00"))
        position_service.realized_profit_since.return_value = Decimal("-9.99")
        position_service.list_active.return_value = []
        trading_service.pool_item_service.list_marked_for_trading.return_value = [make_pool_item(buy=Decimal("6.00"))]
        trading_service.steam_service.get_order_book.return_value = make_book(Decimal("6.82"))
        trading_service.steam_service.create_buy_order.return_value = "BUY-9"

        await trading_service._open_new_positions()

        trading_service.steam_service.create_buy_order.assert_awaited_once()


@pytest.mark.asyncio
class TestCooldownAfterLoss:
    async def test_skips_an_item_that_just_lost_money(self, trading_service, position_service):
        position_service.list_active.return_value = []
        position_service.last_loss_at.return_value = datetime.now(timezone.utc) - timedelta(hours=1)
        trading_service.pool_item_service.list_marked_for_trading.return_value = [make_pool_item()]

        await trading_service._open_new_positions()

        trading_service.steam_service.get_order_book.assert_not_awaited()
        trading_service.steam_service.create_buy_order.assert_not_awaited()

    async def test_trades_again_once_the_cooldown_has_passed(self, trading_service, position_service):
        position_service.list_active.return_value = []
        position_service.last_loss_at.return_value = datetime.now(timezone.utc) - timedelta(hours=25)
        trading_service.pool_item_service.list_marked_for_trading.return_value = [make_pool_item(buy=Decimal("6.00"))]
        trading_service.steam_service.get_order_book.return_value = make_book(Decimal("6.82"))
        trading_service.steam_service.create_buy_order.return_value = "BUY-9"

        await trading_service._open_new_positions()

        trading_service.steam_service.create_buy_order.assert_awaited_once()

    async def test_a_zero_cooldown_never_blocks(self, trading_service, position_service):
        trading_service.settings_service.get_settings.return_value = make_settings(cooldown_after_loss_hours=0)
        position_service.list_active.return_value = []
        position_service.last_loss_at.return_value = datetime.now(timezone.utc)
        trading_service.pool_item_service.list_marked_for_trading.return_value = [make_pool_item(buy=Decimal("6.00"))]
        trading_service.steam_service.get_order_book.return_value = make_book(Decimal("6.82"))
        trading_service.steam_service.create_buy_order.return_value = "BUY-9"

        await trading_service._open_new_positions()

        trading_service.steam_service.create_buy_order.assert_awaited_once()
