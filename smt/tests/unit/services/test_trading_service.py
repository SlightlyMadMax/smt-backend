from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from smt.schemas.position import PositionStatus
from smt.services.trading import TradingService


def make_position(position_id: int, status: PositionStatus, asset_id=None, sell_order_id=None):
    return SimpleNamespace(
        id=position_id,
        pool_item_hash="AK-47 | Redline (Field-Tested)",
        pool_item=SimpleNamespace(app_id="730", context_id="2"),
        asset_id=asset_id,
        sell_order_id=sell_order_id,
        sell_price=Decimal("15.00"),
        status=status,
    )


def make_listing(listing_id: str, asset_id: str, need_confirmation: bool = False):
    listing = {"listing_id": listing_id, "description": {"id": asset_id}}
    if need_confirmation:
        listing["need_confirmation"] = True
    return listing


@pytest.fixture
def position_service():
    service = AsyncMock()
    service.list_by_status.return_value = []
    return service


@pytest.fixture
def trading_service(position_service):
    return TradingService(
        steam_service=AsyncMock(),
        inventory_service=AsyncMock(),
        position_service=position_service,
        pool_item_service=AsyncMock(),
        settings_service=AsyncMock(),
    )


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
