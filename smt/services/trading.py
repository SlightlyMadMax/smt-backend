import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Sequence, Tuple

from steampy.models import GameOptions

from smt.db.models import Item, PoolItem
from smt.exceptions import OrderBookUnavailable
from smt.logger import get_logger
from smt.schemas.position import PositionCreate, PositionStatus
from smt.services.inventory import InventoryService
from smt.services.pool import PoolService
from smt.services.position import PositionService
from smt.services.settings import SettingsService
from smt.services.steam import SteamService


logger = get_logger("services.trading")

CANCEL_GRACE_PERIOD = timedelta(minutes=10)

# Steam allows active buy orders worth up to ten times the wallet balance, and does not
# hold the funds until an order actually fills.
OPEN_ORDER_EXPOSURE_MULTIPLIER = Decimal("10")


class TradingService:
    def __init__(
        self,
        steam_service: SteamService,
        inventory_service: InventoryService,
        position_service: PositionService,
        pool_item_service: PoolService,
        settings_service: SettingsService,
    ):
        self.steam_service = steam_service
        self.inventory_service = inventory_service
        self.position_service = position_service
        self.pool_item_service = pool_item_service
        self.settings_service = settings_service

    async def run_cycle(self) -> None:
        logger.info("Starting trading cycle")
        start = time.monotonic()
        try:
            listings = await self.steam_service.get_my_market_listings()
            assets = await self._snapshot_all_items()
            buy_orders = list(listings.get("buy_orders", {}).values())
            sell_listings = list(listings.get("sell_listings", {}).values())

            settings = await self.settings_service.get_settings()
            await self._reconcile_orders(buy_orders, sell_listings, settings.cancel_untracked_orders)

            await self._sync_open_to_bought(assets, buy_orders)
            await self._resolve_pending_listings(sell_listings)
            await self._sync_listed_to_closed(sell_listings)
            await self._list_bought_positions()

            if not settings.emergency_stop:
                await self._open_new_positions()
        except Exception:
            logger.exception("Error in trading cycle")

        logger.info(f"Trading cycle complete in {time.monotonic() - start:.2f} s.")

    async def _snapshot_all_items(
        self,
    ) -> Dict[Tuple[str, str], Dict[str, List[Item]]]:
        """
        Refresh the stored inventory for every game in the pool.

        Returns a mapping per game:
          (app_id, context_id) -> { market_hash_name: [Item, ...] }
        """
        pool_items: Sequence[PoolItem] = await self.pool_item_service.list()
        games: Dict[Tuple[str, str], List[PoolItem]] = {}
        for item in pool_items:
            games.setdefault((item.app_id, item.context_id), []).append(item)

        all_assets: Dict[Tuple[str, str], Dict[str, List[Item]]] = {}
        for app_id, ctx_id in games:
            all_assets[(app_id, ctx_id)] = await self.inventory_service.sync_snapshot(GameOptions(app_id, ctx_id))
        return all_assets

    async def _reconcile_orders(self, buy_orders: list, sell_listings: list, cancel: bool) -> None:
        """
        Report Steam orders and listings that no active position accounts for.

        An order that is live on Steam while its position is already CANCELLED or CLOSED
        means the two views drifted apart, which is how duplicate orders appear.
        """
        active = await self.position_service.list_active()
        known_order_ids = {pos.buy_order_id for pos in active if pos.buy_order_id}
        known_listing_ids = {pos.sell_order_id for pos in active if pos.sell_order_id}
        known_asset_ids = {pos.asset_id for pos in active if pos.asset_id}

        for order in buy_orders:
            order_id = order.get("order_id")
            if not order_id or order_id in known_order_ids:
                continue
            logger.warning(
                f"Untracked buy order {order_id} on Steam: {order.get('quantity')} x "
                f"{order.get('item_name')} at {order.get('price')}. No active position refers to it."
            )
            if cancel:
                await self.steam_service.cancel_buy_order(order_id)

        for listing in sell_listings:
            listing_id = listing.get("listing_id")
            asset_id = self._listing_asset_id(listing)
            if not listing_id or listing_id in known_listing_ids or asset_id in known_asset_ids:
                continue
            logger.warning(
                f"Untracked sell listing {listing_id} on Steam for asset {asset_id}. "
                f"No active position refers to it."
            )
            if cancel:
                await self.steam_service.cancel_sell_listing(listing_id)

    async def _sync_open_to_bought(
        self, assets: Dict[Tuple[str, str], Dict[str, List[Item]]], buy_orders: list
    ) -> None:
        """
        Resolve OPEN positions whose buy order is no longer active on Steam.

        A position is only matched against an asset that entered the inventory after
        the position was opened, so items owned beforehand are never claimed. When no
        such asset exists the order did not fill and the position is cancelled.
        """
        open_positions = await self.position_service.list_by_status(PositionStatus.OPEN)
        active_buy_order_ids = {order["order_id"] for order in buy_orders if "order_id" in order}
        claimed = {pos.asset_id for pos in await self.position_service.list() if pos.asset_id}
        now = datetime.now(timezone.utc)

        for pos in open_positions:
            if pos.buy_order_id in active_buy_order_ids:
                continue

            key = (pos.pool_item.app_id, pos.pool_item.context_id)
            available = sorted(
                assets.get(key, {}).get(pos.pool_item_hash, []),
                key=lambda item: item.first_seen_at,
            )
            candidate = next(
                (item for item in available if item.id not in claimed and item.first_seen_at > pos.created_at),
                None,
            )

            if candidate:
                logger.info(
                    f"Buy order {pos.buy_order_id} disappeared and item {candidate.id} acquired at "
                    f"{candidate.first_seen_at} was found for Position {pos.id}. Marking it as BOUGHT."
                )
                await self.position_service.mark_as_bought(
                    position_id=pos.id,
                    asset_id=candidate.id,
                )
                claimed.add(candidate.id)
                continue

            if now - pos.created_at < CANCEL_GRACE_PERIOD:
                logger.info(
                    f"Buy order {pos.buy_order_id} for Position {pos.id} is not listed yet, waiting before cancelling."
                )
                continue

            logger.warning(
                f"Buy order {pos.buy_order_id} for Position {pos.id} disappeared without a matching new item. "
                f"Marking the position as CANCELLED."
            )
            await self.position_service.mark_as_cancelled(position_id=pos.id)

    async def _list_bought_positions(self) -> None:
        """Place a sell order for each BOUGHT position."""
        bought_positions = await self.position_service.list_by_status(PositionStatus.BOUGHT)
        for pos in bought_positions:
            logger.info(
                f"Placing a sell order for Position {pos.id}, market_hash_name: {pos.pool_item_hash}, price: {pos.sell_price} rub."
            )
            await self.steam_service.create_sell_order(
                asset_id=pos.asset_id,
                game=GameOptions(pos.pool_item.app_id, pos.pool_item.context_id),
                price=pos.sell_price,
            )
            await self.position_service.mark_as_listing_pending(position_id=pos.id)

    @staticmethod
    def _listing_asset_id(listing: dict) -> Optional[str]:
        return (listing.get("description") or {}).get("id")

    async def _resolve_pending_listings(self, listings: List) -> None:
        """Attach the Steam listing id to LISTING_PENDING positions by matching on asset_id."""
        pending_positions = await self.position_service.list_by_status(PositionStatus.LISTING_PENDING)
        if not pending_positions:
            return

        asset_to_listing = {
            asset_id: li.get("listing_id")
            for li in listings
            if not li.get("need_confirmation") and (asset_id := self._listing_asset_id(li))
        }

        for pos in pending_positions:
            listing_id = asset_to_listing.get(pos.asset_id)
            if not listing_id:
                logger.warning(f"Position {pos.id}: no active listing found yet for asset {pos.asset_id}.")
                continue

            logger.info(f"Position {pos.id}: resolved listing {listing_id} for asset {pos.asset_id}.")
            await self.position_service.mark_as_listed(position_id=pos.id, sell_order_id=listing_id)

    async def _sync_listed_to_closed(
        self,
        listings: List,
    ) -> None:
        """Mark LISTED positions as CLOSED when sell orders disappear."""
        listed_positions = await self.position_service.list_by_status(PositionStatus.LISTED)
        active_listing_ids = {li.get("listing_id") for li in listings}
        for pos in listed_positions:
            if not pos.sell_order_id:
                logger.warning(f"Position {pos.id} is LISTED without a listing id, skipping.")
                continue
            if pos.sell_order_id not in active_listing_ids:
                logger.info(f"Sell order {pos.sell_order_id} for Position {pos.id} disappeared, closing position.")
                await self.position_service.close(position_id=pos.id)

    async def _open_new_positions(self) -> None:
        """Submit new buy orders for PoolItems flagged for trading, within the configured limits."""
        settings = await self.settings_service.get_settings()
        pool_items = await self.pool_item_service.list_marked_for_trading()
        existing = await self.position_service.list_active()

        day_start = datetime.now(timezone.utc) - timedelta(days=1)
        realized = await self.position_service.realized_profit_since(day_start)
        if realized < -settings.max_daily_loss:
            logger.warning(
                f"Not opening new positions: realized profit over the last 24h is {realized}, "
                f"past the daily loss limit of -{settings.max_daily_loss}."
            )
            return

        free_slots = settings.max_concurrent_trades - len(existing)
        if free_slots <= 0:
            logger.info(
                f"Not opening new positions: {len(existing)} active positions already reach "
                f"the limit of {settings.max_concurrent_trades}."
            )
            return

        try:
            balance = await self.steam_service.get_wallet_balance()
        except Exception as e:
            logger.warning(f"Not opening new positions, the wallet balance is unknown: {e!r}")
            return

        open_positions = [p for p in existing if p.status == PositionStatus.OPEN]
        exposure = sum((p.buy_price for p in open_positions), Decimal("0"))
        allowance = balance * OPEN_ORDER_EXPOSURE_MULTIPLIER - exposure

        logger.info(
            f"Opening positions with {balance} in the wallet, {free_slots} free slots and "
            f"{allowance} of buy order allowance left ({exposure} already committed to open orders)."
        )

        if allowance <= 0:
            logger.info("Open buy orders already reach the allowance, not opening new positions.")
            return

        now = datetime.now(timezone.utc)

        for item in pool_items:
            if free_slots <= 0:
                logger.info("Reached the concurrent trade limit, stopping.")
                break

            existing_positions = [p for p in existing if p.pool_item_hash == item.market_hash_name]
            to_create = min(item.max_listed - len(existing_positions), free_slots)
            if to_create <= 0:
                continue

            committed = sum((p.buy_price for p in existing_positions), Decimal("0"))
            budget_left = settings.max_investment_per_item - committed
            if budget_left <= 0:
                logger.info(
                    f"Skipping {item.market_hash_name}: {committed} already committed reaches "
                    f"the per item limit of {settings.max_investment_per_item}."
                )
                continue

            last_loss = await self.position_service.last_loss_at(item.market_hash_name)
            if last_loss and now - last_loss < timedelta(hours=settings.cooldown_after_loss_hours):
                logger.info(
                    f"Skipping {item.market_hash_name}: it lost money at {last_loss}, "
                    f"still inside the {settings.cooldown_after_loss_hours}h cooldown."
                )
                continue

            buy_price = item.effective_buy_price
            if buy_price is None:
                logger.warning(f"{item.market_hash_name} is marked for trading but has no buy price, skipping.")
                continue

            try:
                book = await self.steam_service.get_order_book(
                    market_hash_name=item.market_hash_name, app_id=item.app_id
                )
            except OrderBookUnavailable as e:
                logger.warning(f"Skipping {item.market_hash_name}, could not read the order book: {e}")
                continue

            lowest_ask = book["lowest_sell_order"]
            if lowest_ask is None:
                logger.warning(f"Skipping {item.market_hash_name}, the order book has no sell orders.")
                continue

            if buy_price >= lowest_ask:
                logger.info(
                    f"Skipping {item.market_hash_name}: buy price {buy_price} is not below the cheapest listing "
                    f"{lowest_ask}, so the order would fill immediately at market instead of waiting for a dip."
                )
                continue

            for _ in range(to_create):
                if buy_price > balance:
                    logger.info(
                        f"Skipping {item.market_hash_name}: a single order of {buy_price} exceeds "
                        f"the wallet balance {balance}."
                    )
                    break

                if buy_price > allowance:
                    logger.info(
                        f"Skipping {item.market_hash_name}: {buy_price} exceeds the remaining buy order "
                        f"allowance {allowance}."
                    )
                    break

                if buy_price > budget_left:
                    logger.info(
                        f"Skipping {item.market_hash_name}: {buy_price} exceeds the remaining per item "
                        f"budget {budget_left}."
                    )
                    break

                logger.info(
                    f"Creating a buy order for {item.market_hash_name}, price: {buy_price} "
                    f"(top bid {book['highest_buy_order']}, cheapest listing {lowest_ask})."
                )
                buy_id = await self.steam_service.create_buy_order(
                    market_hash_name=item.market_hash_name,
                    price=buy_price,
                    game=GameOptions(item.app_id, item.context_id),
                    quantity=1,
                )
                create = PositionCreate(
                    pool_item_hash=item.market_hash_name,
                    buy_order_id=buy_id,
                    buy_price=buy_price,
                    sell_price=item.effective_sell_price,
                )
                await self.position_service.add(create)

                allowance -= buy_price
                budget_left -= buy_price
                free_slots -= 1
