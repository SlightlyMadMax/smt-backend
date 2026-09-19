from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from smt.exceptions import BuyOrderFailed, OrderBookUnavailable, SellOrderFailed, SteamThrottled
from smt.schemas.action_log import ActionKind
from smt.schemas.position import PositionStatus
from smt.services.trading import CANCEL_GRACE_PERIOD, TradingService
from smt.utils.steam import minimum_listing_price


ITEM_HASH = "AK-47 | Redline (Field-Tested)"
GAME_KEY = ("730", "2")
NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def make_position(position_id: int, status: PositionStatus, asset_id=None, sell_order_id=None, created_at=None):
    return SimpleNamespace(
        id=position_id,
        buy_order_id=f"BUY-{position_id}",
        pool_item_hash=ITEM_HASH,
        app_id="730",
        context_id="2",
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
    service.steam_service.get_buy_order_status.return_value = make_order_status()
    position_service.realized_profit_since.return_value = Decimal("0")
    position_service.last_loss_at.return_value = None
    return service


@pytest.fixture
def action_log(trading_service):
    return trading_service.action_log


@pytest.mark.asyncio
class TestResolvePendingListings:
    async def test_matches_listing_by_asset_id(self, trading_service, position_service):
        position_service.list_by_status.return_value = [
            make_position(1, PositionStatus.LISTING_PENDING, asset_id="ASSET-1")
        ]

        await trading_service._resolve_pending_listings([make_listing("LISTING-9", "ASSET-1")], {})

        position_service.mark_as_listed.assert_awaited_once_with(position_id=1, sell_order_id="LISTING-9")

    async def test_ignores_listing_of_a_different_asset(self, trading_service, position_service):
        position_service.list_by_status.return_value = [
            make_position(1, PositionStatus.LISTING_PENDING, asset_id="ASSET-1")
        ]

        await trading_service._resolve_pending_listings([make_listing("LISTING-9", "ASSET-2")], {})

        position_service.mark_as_listed.assert_not_awaited()

    async def test_skips_listings_awaiting_confirmation(self, trading_service, position_service):
        position_service.list_by_status.return_value = [
            make_position(1, PositionStatus.LISTING_PENDING, asset_id="ASSET-1")
        ]

        await trading_service._resolve_pending_listings(
            [make_listing("LISTING-9", "ASSET-1", need_confirmation=True)], {}
        )

        position_service.mark_as_listed.assert_not_awaited()

    async def test_no_listings_leaves_position_pending(self, trading_service, position_service):
        position_service.list_by_status.return_value = [
            make_position(1, PositionStatus.LISTING_PENDING, asset_id="ASSET-1")
        ]

        await trading_service._resolve_pending_listings([], {})

        position_service.mark_as_listed.assert_not_awaited()

    @staticmethod
    def pending(trading_service, position_service, sold=None):
        position = make_position(1, PositionStatus.LISTING_PENDING, asset_id="ASSET-1")
        position.listed_at = NOW - timedelta(minutes=5)
        position_service.list_by_status.return_value = [position]
        position_service.close.return_value = SimpleNamespace(
            sell_price=Decimal("15.00"), net_proceeds=Decimal("12.85"), realized_profit=Decimal("2.85")
        )
        trading_service.steam_service.get_sold_listings.return_value = {
            "sold": sold or {},
            "oldest_event_at": NOW - timedelta(days=7),
        }
        return position

    async def test_closes_a_position_sold_before_its_id_arrived(self, trading_service, position_service):
        """The listing can sell inside the window where we still do not know its id."""
        sold_at = NOW - timedelta(minutes=2)
        self.pending(
            trading_service,
            position_service,
            sold={"LISTING-9": {"sold_at": sold_at, "net_proceeds": Decimal("12.85"), "asset_id": "ASSET-1"}},
        )

        await trading_service._resolve_pending_listings([], {})

        position_service.mark_as_listed.assert_awaited_once_with(position_id=1, sell_order_id="LISTING-9")
        position_service.close.assert_awaited_once_with(position_id=1, sold_at=sold_at, net_proceeds=Decimal("12.85"))

    async def test_a_sale_of_another_asset_closes_nothing(self, trading_service, position_service):
        self.pending(
            trading_service,
            position_service,
            sold={"LISTING-9": {"sold_at": NOW, "net_proceeds": Decimal("12.85"), "asset_id": "ASSET-2"}},
        )

        await trading_service._resolve_pending_listings([], {})

        position_service.close.assert_not_awaited()

    async def test_history_without_asset_ids_closes_nothing(self, trading_service, position_service):
        self.pending(
            trading_service,
            position_service,
            sold={"LISTING-9": {"sold_at": NOW, "net_proceeds": Decimal("12.85"), "asset_id": None}},
        )

        await trading_service._resolve_pending_listings([], {})

        position_service.close.assert_not_awaited()

    async def test_a_sale_beats_a_lookalike_left_in_the_inventory(self, trading_service, position_service):
        """A second copy of the same item must not pass for a cancelled listing."""
        position = self.pending(
            trading_service,
            position_service,
            sold={"LISTING-9": {"sold_at": NOW, "net_proceeds": Decimal("12.85"), "asset_id": "ASSET-1"}},
        )
        assets = {GAME_KEY: {ITEM_HASH: [make_asset("ASSET-7", position.created_at + timedelta(minutes=1))]}}

        await trading_service._resolve_pending_listings([], assets)

        position_service.revert_to_bought.assert_not_awaited()
        position_service.close.assert_awaited_once()

    async def test_a_fresh_pass_only_attaches_ids(self, trading_service, position_service):
        """Right after listing, the stale inventory snapshot still holds the item we just sold off."""
        position = self.pending(trading_service, position_service)
        assets = {GAME_KEY: {ITEM_HASH: [make_asset("ASSET-1", position.created_at + timedelta(minutes=1))]}}

        await trading_service._resolve_pending_listings([], assets, reconcile=False)

        position_service.revert_to_bought.assert_not_awaited()
        position_service.close.assert_not_awaited()
        trading_service.steam_service.get_sold_listings.assert_not_awaited()

    async def test_one_history_read_serves_the_whole_cycle(self, trading_service, position_service):
        self.pending(trading_service, position_service)

        await trading_service._resolve_pending_listings([], {})
        await trading_service._resolve_pending_listings([], {})

        assert trading_service.steam_service.get_sold_listings.await_count == 1


@pytest.mark.asyncio
class TestSyncListedToClosed:
    @staticmethod
    def listed(trading_service, position_service, **kwargs):
        position = make_position(1, PositionStatus.LISTED, asset_id="ASSET-1", sell_order_id="LISTING-9")
        position.listed_at = NOW - timedelta(hours=2)
        position_service.list_by_status.return_value = [position]
        trading_service.steam_service.get_sold_listings.return_value = {
            "sold": {},
            "oldest_event_at": NOW - timedelta(days=7),
            **kwargs,
        }
        return position

    async def test_keeps_position_while_listing_is_active(self, trading_service, position_service):
        self.listed(trading_service, position_service)

        await trading_service._sync_listed_to_closed([make_listing("LISTING-9", "ASSET-1")], {})

        position_service.close.assert_not_awaited()

    async def test_a_missing_listing_alone_is_not_a_sale(self, trading_service, position_service):
        """A failed fetch looks exactly like every listing selling at once."""
        self.listed(trading_service, position_service)

        await trading_service._sync_listed_to_closed([], {})

        position_service.close.assert_not_awaited()

    async def test_an_unaccounted_listing_is_reported(self, trading_service, position_service, action_log):
        self.listed(trading_service, position_service)

        await trading_service._sync_listed_to_closed([], {})

        action_log.record.assert_awaited_once()
        assert action_log.record.await_args.args[0] == ActionKind.LISTING_VANISHED

    async def test_closes_when_the_history_confirms_the_sale(self, trading_service, position_service):
        sold_at = NOW - timedelta(minutes=5)
        self.listed(
            trading_service,
            position_service,
            sold={"LISTING-9": {"sold_at": sold_at, "net_proceeds": Decimal("12.85")}},
        )

        await trading_service._sync_listed_to_closed([], {})

        position_service.close.assert_awaited_once_with(position_id=1, sold_at=sold_at, net_proceeds=Decimal("12.85"))

    async def test_the_sale_wins_even_if_the_listing_still_shows(self, trading_service, position_service):
        """Steam can keep showing a listing for a moment after it sells."""
        self.listed(
            trading_service,
            position_service,
            sold={"LISTING-9": {"sold_at": NOW, "net_proceeds": Decimal("12.85")}},
        )

        await trading_service._sync_listed_to_closed([make_listing("LISTING-9", "ASSET-1")], {})

        position_service.close.assert_awaited_once()

    async def test_says_so_when_the_history_does_not_reach_back(self, trading_service, position_service, action_log):
        position = self.listed(trading_service, position_service)
        position.listed_at = NOW - timedelta(days=30)
        trading_service.steam_service.get_sold_listings.return_value["oldest_event_at"] = NOW - timedelta(hours=1)

        await trading_service._sync_listed_to_closed([], {})

        assert "does not reach back" in action_log.record.await_args.args[1]

    async def test_skips_position_without_listing_id(self, trading_service, position_service):
        position_service.list_by_status.return_value = [
            make_position(1, PositionStatus.LISTED, asset_id="ASSET-1", sell_order_id=None)
        ]
        trading_service.steam_service.get_sold_listings.return_value = {"sold": {}, "oldest_event_at": None}

        await trading_service._sync_listed_to_closed([], {})

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

        position_service.mark_as_bought.assert_awaited_once_with(position_id=1, asset_id="NEW-1", buy_price=None)
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


def make_pool_item(buy=Decimal("6.00"), sell=Decimal("7.77"), max_listed=1, name=ITEM_HASH):
    return SimpleNamespace(
        market_hash_name=name,
        app_id="440",
        context_id="2",
        max_listed=max_listed,
        effective_buy_price=buy,
        effective_sell_price=sell,
        potential_profit=Decimal("0.80"),
        median_hold_hours=Decimal("12.0"),
        days_to_clear=Decimal("0.5"),
        return_on_capital_30d=Decimal("95.0"),
    )


def make_pool_items(count: int, **kwargs):
    """Steam takes one buy order per item, so several orders means several items."""
    return [make_pool_item(name=f"Item {n}", **kwargs) for n in range(count)]


def make_order_status(active=False, purchased=1, paid=None):
    return {
        "active": active,
        "purchased": purchased,
        "quantity": 1,
        "quantity_remaining": 1 - purchased,
        "paid": paid,
        "purchases": [],
    }


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

    async def test_buys_at_the_market_price_when_it_is_cheaper(self, trading_service, position_service):
        """A market cheaper than our target is a better deal than the one we planned."""
        trading_service.pool_item_service.list_marked_for_trading.return_value = [make_pool_item(buy=Decimal("6.91"))]
        position_service.list_active.return_value = []
        trading_service.steam_service.get_order_book.return_value = make_book(Decimal("6.82"))
        trading_service.steam_service.create_buy_order.return_value = "BUY-9"

        await trading_service._open_new_positions()

        assert trading_service.steam_service.create_buy_order.await_args.kwargs["price"] == Decimal("6.82")

    async def test_the_position_records_what_it_actually_cost(self, trading_service, position_service):
        trading_service.pool_item_service.list_marked_for_trading.return_value = [make_pool_item(buy=Decimal("6.91"))]
        position_service.list_active.return_value = []
        trading_service.steam_service.get_order_book.return_value = make_book(Decimal("6.82"))
        trading_service.steam_service.create_buy_order.return_value = "BUY-9"

        await trading_service._open_new_positions()

        assert position_service.add.await_args.args[0].buy_price == Decimal("6.82")

    async def test_our_own_price_is_kept_when_the_market_is_dearer(self, trading_service, position_service):
        trading_service.pool_item_service.list_marked_for_trading.return_value = [make_pool_item(buy=Decimal("6.00"))]
        position_service.list_active.return_value = []
        trading_service.steam_service.get_order_book.return_value = make_book(Decimal("6.82"))
        trading_service.steam_service.create_buy_order.return_value = "BUY-9"

        await trading_service._open_new_positions()

        assert trading_service.steam_service.create_buy_order.await_args.kwargs["price"] == Decimal("6.00")

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
        trading_service.pool_item_service.list_marked_for_trading.return_value = make_pool_items(3, buy=Decimal("6.00"))
        position_service.list_active.return_value = []
        trading_service.steam_service.get_order_book.return_value = make_book(Decimal("6.82"))
        trading_service.steam_service.create_buy_order.return_value = "BUY-9"

        await trading_service._open_new_positions()

        assert trading_service.steam_service.get_order_book.await_count == 3
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
        trading_service.pool_item_service.list_marked_for_trading.return_value = make_pool_items(3, buy=Decimal("6.00"))
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
        trading_service.pool_item_service.list_marked_for_trading.return_value = make_pool_items(
            20, buy=Decimal("1.50")
        )
        trading_service.steam_service.get_order_book.return_value = make_book(Decimal("6.82"))
        trading_service.steam_service.create_buy_order.return_value = "BUY-9"

        await trading_service._open_new_positions()

        assert trading_service.steam_service.create_buy_order.await_count == 13

    async def test_existing_open_orders_eat_into_the_allowance(self, trading_service, position_service):
        held = make_position(1, PositionStatus.OPEN)
        held.buy_price = Decimal("18.00")
        position_service.list_active.return_value = [held]
        trading_service.steam_service.get_wallet_balance.return_value = Decimal("2.00")
        trading_service.pool_item_service.list_marked_for_trading.return_value = make_pool_items(
            20, buy=Decimal("1.00")
        )
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
        trading_service.pool_item_service.list_marked_for_trading.return_value = make_pool_items(5, buy=Decimal("1.00"))
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
            max_investment_per_item=Decimal("5.00")
        )
        position_service.list_active.return_value = []
        trading_service.pool_item_service.list_marked_for_trading.return_value = [
            make_pool_item(buy=Decimal("6.00"), max_listed=5)
        ]
        trading_service.steam_service.get_order_book.return_value = make_book(Decimal("6.82"))

        await trading_service._open_new_positions()

        trading_service.steam_service.create_buy_order.assert_not_awaited()

    async def test_counts_money_already_committed_to_the_item(self, trading_service, position_service):
        trading_service.settings_service.get_settings.return_value = make_settings(
            max_investment_per_item=Decimal("18.00")
        )
        held = make_position(1, PositionStatus.BOUGHT)
        held.buy_price = Decimal("15.00")
        position_service.list_active.return_value = [held]
        trading_service.pool_item_service.list_marked_for_trading.return_value = [
            make_pool_item(buy=Decimal("6.00"), max_listed=5)
        ]
        trading_service.steam_service.get_order_book.return_value = make_book(Decimal("6.82"))

        await trading_service._open_new_positions()

        trading_service.steam_service.create_buy_order.assert_not_awaited()


@pytest.mark.asyncio
class TestOneBuyOrderPerItem:
    """Steam refuses a second active buy order for the same item."""

    async def test_only_one_order_per_item_however_many_slots(self, trading_service, position_service):
        position_service.list_active.return_value = []
        trading_service.pool_item_service.list_marked_for_trading.return_value = [
            make_pool_item(buy=Decimal("6.00"), max_listed=5)
        ]
        trading_service.steam_service.get_order_book.return_value = make_book(Decimal("6.82"))
        trading_service.steam_service.create_buy_order.return_value = "BUY-9"

        await trading_service._open_new_positions()

        assert trading_service.steam_service.create_buy_order.await_count == 1

    async def test_an_item_with_an_order_waiting_is_skipped(self, trading_service, position_service):
        position_service.list_active.return_value = [make_position(1, PositionStatus.OPEN)]
        trading_service.pool_item_service.list_marked_for_trading.return_value = [
            make_pool_item(buy=Decimal("6.00"), max_listed=5)
        ]
        trading_service.steam_service.get_order_book.return_value = make_book(Decimal("6.82"))

        await trading_service._open_new_positions()

        trading_service.steam_service.create_buy_order.assert_not_awaited()

    async def test_a_bought_position_does_not_block_the_next_order(self, trading_service, position_service):
        position_service.list_active.return_value = [make_position(1, PositionStatus.BOUGHT)]
        trading_service.pool_item_service.list_marked_for_trading.return_value = [
            make_pool_item(buy=Decimal("6.00"), max_listed=5)
        ]
        trading_service.steam_service.get_order_book.return_value = make_book(Decimal("6.82"))
        trading_service.steam_service.create_buy_order.return_value = "BUY-9"

        await trading_service._open_new_positions()

        assert trading_service.steam_service.create_buy_order.await_count == 1

    async def test_a_refusal_does_not_stop_the_other_items(self, trading_service, position_service, action_log):
        position_service.list_active.return_value = []
        trading_service.pool_item_service.list_marked_for_trading.return_value = make_pool_items(3, buy=Decimal("6.00"))
        trading_service.steam_service.get_order_book.return_value = make_book(Decimal("6.82"))
        trading_service.steam_service.create_buy_order.side_effect = [
            BuyOrderFailed("Steam said no"),
            "BUY-2",
            "BUY-3",
        ]

        await trading_service._open_new_positions()

        assert trading_service.steam_service.create_buy_order.await_count == 3
        assert position_service.add.await_count == 2
        assert action_log.record.await_args_list[0].args[0] == ActionKind.BUY_ORDER_REFUSED

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


@pytest.mark.asyncio
class TestRecoveringACancelledListing:
    """Steam issues a new asset id when a cancelled listing returns the item."""

    @staticmethod
    def setup(trading_service, position_service, status=PositionStatus.LISTED, first_seen_at=None):
        position = make_position(1, status, asset_id="OLD-ASSET", sell_order_id="LISTING-9")
        position.listed_at = NOW - timedelta(hours=2)
        position_service.list_by_status.return_value = [position]
        trading_service.steam_service.get_sold_listings.return_value = {
            "sold": {},
            "oldest_event_at": NOW - timedelta(days=7),
        }
        assets = {
            GAME_KEY: {
                ITEM_HASH: [make_asset("NEW-ASSET", first_seen_at or (NOW - timedelta(minutes=10)))],
            }
        }
        return position, assets

    async def test_the_item_coming_back_means_the_listing_was_cancelled(self, trading_service, position_service):
        _, assets = self.setup(trading_service, position_service)

        await trading_service._sync_listed_to_closed([], assets)

        position_service.revert_to_bought.assert_awaited_once_with(position_id=1, asset_id="NEW-ASSET")
        position_service.close.assert_not_awaited()

    async def test_it_is_journalled(self, trading_service, position_service, action_log):
        _, assets = self.setup(trading_service, position_service)

        await trading_service._sync_listed_to_closed([], assets)

        assert action_log.record.await_args.args[0] == ActionKind.LISTING_CANCELLED

    async def test_nothing_in_the_inventory_leaves_the_position_alone(self, trading_service, position_service):
        self.setup(trading_service, position_service)

        await trading_service._sync_listed_to_closed([], {})

        position_service.revert_to_bought.assert_not_awaited()

    async def test_it_will_not_take_an_item_older_than_the_position(self, trading_service, position_service):
        """An item the account already owned is not ours to relist."""
        _, assets = self.setup(trading_service, position_service, first_seen_at=NOW - timedelta(days=30))

        await trading_service._sync_listed_to_closed([], assets)

        position_service.revert_to_bought.assert_not_awaited()

    async def test_it_will_not_take_an_item_another_position_holds(self, trading_service, position_service):
        _, assets = self.setup(trading_service, position_service)
        position_service.list.return_value = [
            make_position(2, PositionStatus.BOUGHT, asset_id="NEW-ASSET"),
        ]

        await trading_service._sync_listed_to_closed([], assets)

        position_service.revert_to_bought.assert_not_awaited()

    async def test_a_confirmed_sale_wins_over_recovery(self, trading_service, position_service):
        _, assets = self.setup(trading_service, position_service)
        trading_service.steam_service.get_sold_listings.return_value["sold"] = {
            "LISTING-9": {"sold_at": NOW, "net_proceeds": Decimal("12.85")}
        }

        await trading_service._sync_listed_to_closed([], assets)

        position_service.close.assert_awaited_once()
        position_service.revert_to_bought.assert_not_awaited()

    async def test_a_pending_listing_recovers_too(self, trading_service, position_service):
        _, assets = self.setup(trading_service, position_service, status=PositionStatus.LISTING_PENDING)

        await trading_service._resolve_pending_listings([], assets)

        position_service.revert_to_bought.assert_awaited_once_with(position_id=1, asset_id="NEW-ASSET")


@pytest.mark.asyncio
class TestBuyOrderStatus:
    """Steam can say directly whether an order filled, instead of us inferring it."""

    @staticmethod
    def open_position(position_service, asset=None):
        position_service.list_by_status.return_value = [make_position(1, PositionStatus.OPEN)]
        position_service.list.return_value = []
        return {GAME_KEY: {ITEM_HASH: [make_asset(asset, NOW)]}} if asset else {}

    async def test_an_order_still_open_is_left_alone(self, trading_service, position_service):
        assets = self.open_position(position_service)
        trading_service.steam_service.get_buy_order_status.return_value = make_order_status(active=True, purchased=0)

        await trading_service._sync_open_to_bought(assets, [])

        position_service.mark_as_bought.assert_not_awaited()
        position_service.mark_as_cancelled.assert_not_awaited()

    async def test_a_cancelled_order_is_closed_without_waiting(self, trading_service, position_service):
        """Steam saying so beats the grace period."""
        position_service.list_by_status.return_value = [make_position(1, PositionStatus.OPEN, created_at=NOW)]
        position_service.list.return_value = []
        trading_service.steam_service.get_buy_order_status.return_value = make_order_status(active=False, purchased=0)

        await trading_service._sync_open_to_bought({}, [])

        position_service.mark_as_cancelled.assert_awaited_once_with(position_id=1)

    async def test_the_price_steam_reports_is_recorded(self, trading_service, position_service):
        assets = self.open_position(position_service, asset="NEW-1")
        trading_service.steam_service.get_buy_order_status.return_value = make_order_status(
            purchased=1, paid=Decimal("3.08")
        )

        await trading_service._sync_open_to_bought(assets, [])

        position_service.mark_as_bought.assert_awaited_once_with(
            position_id=1, asset_id="NEW-1", buy_price=Decimal("3.08")
        )

    async def test_a_failed_status_call_does_not_stop_the_cycle(self, trading_service, position_service):
        assets = self.open_position(position_service, asset="NEW-1")
        trading_service.steam_service.get_buy_order_status.side_effect = RuntimeError("steam is down")

        await trading_service._sync_open_to_bought(assets, [])

        position_service.mark_as_bought.assert_awaited_once_with(position_id=1, asset_id="NEW-1", buy_price=None)


@pytest.mark.asyncio
class TestListingWithinTheCycle:
    @staticmethod
    def setup(trading_service, position_service, second_listing):
        bought = make_position(1, PositionStatus.BOUGHT, asset_id="ASSET-1")
        pending = make_position(1, PositionStatus.LISTING_PENDING, asset_id="ASSET-1")
        by_status = {PositionStatus.BOUGHT: [bought]}

        async def by_status_lookup(status):
            return by_status.get(status, [])

        def listed_now(position_id):
            by_status[PositionStatus.BOUGHT] = []
            by_status[PositionStatus.LISTING_PENDING] = [pending]

        position_service.list_by_status.side_effect = by_status_lookup
        position_service.list_active.return_value = []
        position_service.mark_as_listing_pending.side_effect = listed_now
        trading_service.pool_item_service.list.return_value = []
        trading_service.pool_item_service.list_marked_for_trading.return_value = []
        trading_service.steam_service.get_my_market_listings.side_effect = [
            {"buy_orders": {}, "sell_listings": {}},
            {"buy_orders": {}, "sell_listings": {"L": second_listing}},
        ]

    async def test_a_new_listing_is_matched_without_waiting_a_cycle(self, trading_service, position_service):
        self.setup(trading_service, position_service, make_listing("LISTING-9", "ASSET-1"))

        await trading_service.run_cycle()

        position_service.mark_as_listed.assert_awaited_once_with(position_id=1, sell_order_id="LISTING-9")

    async def test_steam_is_not_asked_again_when_nothing_was_listed(self, trading_service, position_service):
        self.setup(trading_service, position_service, make_listing("LISTING-9", "ASSET-1"))
        position_service.list_by_status.side_effect = None
        position_service.list_by_status.return_value = []

        await trading_service.run_cycle()

        assert trading_service.steam_service.get_my_market_listings.await_count == 1


@pytest.mark.asyncio
class TestListingWhatWeBought:
    @staticmethod
    def bought(trading_service, position_service, sell_price=Decimal("15.00")):
        position = make_position(1, PositionStatus.BOUGHT, asset_id="ASSET-1")
        position.sell_price = sell_price
        position_service.list_by_status.return_value = [position]
        return position

    async def test_a_price_under_the_steam_floor_is_not_sent(self, trading_service, position_service, action_log):
        """Steam refuses these outright, and the refusal used to abort the whole cycle."""
        self.bought(trading_service, position_service, sell_price=Decimal("2.00"))

        listed = await trading_service._list_bought_positions()

        assert listed == 0
        trading_service.steam_service.create_sell_order.assert_not_awaited()
        position_service.mark_as_listing_pending.assert_not_awaited()
        assert action_log.record.await_args.args[0] == ActionKind.SELL_ORDER_REFUSED

    async def test_a_price_on_the_floor_is_sent(self, trading_service, position_service):
        self.bought(trading_service, position_service, sell_price=minimum_listing_price())

        assert await trading_service._list_bought_positions() == 1

    async def test_a_refused_listing_does_not_stop_the_others(self, trading_service, position_service):
        first = make_position(1, PositionStatus.BOUGHT, asset_id="ASSET-1")
        second = make_position(2, PositionStatus.BOUGHT, asset_id="ASSET-2")
        position_service.list_by_status.return_value = [first, second]
        trading_service.steam_service.create_sell_order.side_effect = [SellOrderFailed("no"), None]

        listed = await trading_service._list_bought_positions()

        assert listed == 1
        position_service.mark_as_listing_pending.assert_awaited_once_with(position_id=2)

    async def test_a_refused_listing_is_journalled(self, trading_service, position_service, action_log):
        self.bought(trading_service, position_service)
        trading_service.steam_service.create_sell_order.side_effect = SellOrderFailed("item is not marketable")

        await trading_service._list_bought_positions()

        assert action_log.record.await_args.args[0] == ActionKind.SELL_ORDER_REFUSED


@pytest.mark.asyncio
class TestEmergencyStop:
    @staticmethod
    def stopped(trading_service, position_service):
        position_service.list_active.return_value = []
        position_service.list_by_status.return_value = [make_position(1, PositionStatus.BOUGHT, asset_id="ASSET-1")]
        trading_service.pool_item_service.list.return_value = []
        trading_service.settings_service.get_settings.return_value = make_settings()
        trading_service.settings_service.get_settings.return_value.emergency_stop = True
        trading_service.steam_service.get_my_market_listings.return_value = {"buy_orders": {}, "sell_listings": {}}

    async def test_nothing_is_listed_again(self, trading_service, position_service):
        """Otherwise the bot puts back every listing you cancel by hand."""
        self.stopped(trading_service, position_service)

        await trading_service.run_cycle()

        trading_service.steam_service.create_sell_order.assert_not_awaited()

    async def test_nothing_is_bought(self, trading_service, position_service):
        self.stopped(trading_service, position_service)

        await trading_service.run_cycle()

        trading_service.steam_service.create_buy_order.assert_not_awaited()


@pytest.mark.asyncio
class TestTheForecastTravelsWithThePosition:
    async def test_the_pool_estimate_is_recorded_when_the_order_goes_in(self, trading_service, position_service):
        """Later the pool re-estimates or the item leaves it; the trade must keep what it was opened on."""
        position_service.list_active.return_value = []
        trading_service.pool_item_service.list_marked_for_trading.return_value = [make_pool_item()]
        trading_service.steam_service.get_order_book.return_value = make_book(lowest_ask=Decimal("9.00"))
        trading_service.steam_service.create_buy_order.return_value = "BUY-9"

        await trading_service._open_new_positions()

        created = position_service.add.await_args.args[0]
        assert created.forecast_profit == Decimal("0.80")
        assert created.forecast_hold_hours == Decimal("12.0")
        assert created.forecast_days_to_clear == Decimal("0.5")
        assert created.forecast_return_30d == Decimal("95.0")


@pytest.mark.asyncio
class TestTheStopWithdrawsBuyOrders:
    @staticmethod
    def stopped(trading_service, position_service, *open_positions):
        async def by_status(status):
            return list(open_positions) if status == PositionStatus.OPEN else []

        position_service.list_by_status.side_effect = by_status
        position_service.list_active.return_value = list(open_positions)
        trading_service.pool_item_service.list.return_value = []
        trading_service.settings_service.get_settings.return_value = make_settings()
        trading_service.settings_service.get_settings.return_value.emergency_stop = True
        trading_service.steam_service.get_my_market_listings.return_value = {
            "buy_orders": {p.buy_order_id: {"order_id": p.buy_order_id} for p in open_positions},
            "sell_listings": {},
        }

    async def test_an_untouched_order_is_withdrawn_and_written_off(self, trading_service, position_service, action_log):
        """A live order keeps spending money on items a stopped bot will never list."""
        self.stopped(trading_service, position_service, make_position(1, PositionStatus.OPEN))
        trading_service.steam_service.get_buy_order_status.return_value = make_order_status(active=False, purchased=0)

        await trading_service.run_cycle()

        trading_service.steam_service.cancel_buy_order.assert_awaited_once_with("BUY-1")
        position_service.mark_as_cancelled.assert_awaited_once_with(position_id=1)
        assert action_log.record.await_args.args[0] == ActionKind.POSITION_CANCELLED

    async def test_an_order_that_filled_first_is_not_written_off(self, trading_service, position_service):
        """The item is already ours; the next cycle has to find it and record it as bought."""
        self.stopped(trading_service, position_service, make_position(1, PositionStatus.OPEN))
        trading_service.steam_service.get_buy_order_status.return_value = make_order_status(active=False, purchased=1)

        await trading_service.run_cycle()

        trading_service.steam_service.cancel_buy_order.assert_awaited_once()
        position_service.mark_as_cancelled.assert_not_awaited()

    async def test_an_unconfirmed_withdrawal_is_left_for_the_next_cycle(self, trading_service, position_service):
        self.stopped(trading_service, position_service, make_position(1, PositionStatus.OPEN))
        trading_service.steam_service.get_buy_order_status.side_effect = RuntimeError("429")

        await trading_service.run_cycle()

        position_service.mark_as_cancelled.assert_not_awaited()

    async def test_one_refused_cancellation_does_not_stop_the_rest(self, trading_service, position_service):
        self.stopped(
            trading_service,
            position_service,
            make_position(1, PositionStatus.OPEN),
            make_position(2, PositionStatus.OPEN),
        )
        trading_service.steam_service.cancel_buy_order.side_effect = [RuntimeError("refused"), None]
        trading_service.steam_service.get_buy_order_status.return_value = make_order_status(active=False, purchased=0)

        await trading_service.run_cycle()

        position_service.mark_as_cancelled.assert_awaited_once_with(position_id=2)

    async def test_nothing_is_withdrawn_while_trading_runs(self, trading_service, position_service):
        self.stopped(trading_service, position_service, make_position(1, PositionStatus.OPEN))
        trading_service.settings_service.get_settings.return_value.emergency_stop = False
        trading_service.pool_item_service.list_marked_for_trading.return_value = []

        await trading_service.run_cycle()

        trading_service.steam_service.cancel_buy_order.assert_not_awaited()


@pytest.mark.asyncio
class TestInventoryUnavailable:
    @staticmethod
    def setup(trading_service, position_service):
        position_service.list_active.return_value = []
        position_service.list_by_status.return_value = []
        trading_service.pool_item_service.list.return_value = [
            SimpleNamespace(app_id="730", context_id="2", market_hash_name=ITEM_HASH)
        ]
        trading_service.pool_item_service.list_marked_for_trading.return_value = []
        trading_service.steam_service.get_my_market_listings.return_value = {"buy_orders": {}, "sell_listings": {}}
        trading_service.inventory_service.sync_snapshot.side_effect = SteamThrottled("wait 300s")

    async def test_an_unknown_inventory_is_not_an_empty_one(self, trading_service, position_service):
        """Feeding an empty snapshot in would book every filled buy order as cancelled."""
        self.setup(trading_service, position_service)

        assert await trading_service._snapshot_all_items() is None

    async def test_open_positions_are_left_alone(self, trading_service, position_service):
        self.setup(trading_service, position_service)

        await trading_service.run_cycle()

        position_service.mark_as_cancelled.assert_not_awaited()
        position_service.mark_as_bought.assert_not_awaited()

    async def test_the_rest_of_the_cycle_still_runs(self, trading_service, position_service, action_log):
        self.setup(trading_service, position_service)

        await trading_service.run_cycle()

        action_log.record.assert_not_awaited()
        trading_service.settings_service.get_settings.assert_awaited()


@pytest.mark.asyncio
class TestPacing:
    async def test_being_paced_is_not_a_failure(self, trading_service, action_log):
        """Waiting out a Steam limit should not fill the journal with errors."""
        trading_service.steam_service.get_my_market_listings.side_effect = SteamThrottled("wait 90s")

        await trading_service.run_cycle()

        action_log.record.assert_not_awaited()
