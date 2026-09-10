import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Sequence, Tuple

from steampy.models import GameOptions

from smt.db.models import Item, PoolItem
from smt.exceptions import BuyOrderFailed, OrderBookUnavailable, SellOrderFailed, SteamThrottled
from smt.logger import get_logger
from smt.schemas.action_log import ActionKind, ActionLevel
from smt.schemas.position import PositionCreate, PositionStatus
from smt.services.action_log import ActionLogService
from smt.services.inventory import InventoryService
from smt.services.pool import PoolService
from smt.services.position import PositionService
from smt.services.settings import SettingsService
from smt.services.steam import SteamService
from smt.utils.steam import minimum_listing_price


logger = get_logger("services.trading")

CANCEL_GRACE_PERIOD = timedelta(minutes=10)

OPEN_ORDER_EXPOSURE_MULTIPLIER = Decimal("10")


class TradingService:
    def __init__(
        self,
        steam_service: SteamService,
        inventory_service: InventoryService,
        position_service: PositionService,
        pool_item_service: PoolService,
        settings_service: SettingsService,
        action_log: ActionLogService,
    ):
        self.steam_service = steam_service
        self.inventory_service = inventory_service
        self.position_service = position_service
        self.pool_item_service = pool_item_service
        self.settings_service = settings_service
        self.action_log = action_log
        self._sold_cache: Optional[dict] = None

    async def run_cycle(self) -> None:
        logger.info("Starting trading cycle")
        start = time.monotonic()
        self._sold_cache = None
        try:
            listings = await self.steam_service.get_my_market_listings()
            assets = await self._snapshot_all_items()
            buy_orders = list(listings.get("buy_orders", {}).values())
            sell_listings = list(listings.get("sell_listings", {}).values())

            settings = await self.settings_service.get_settings()
            await self._reconcile_orders(buy_orders, sell_listings, settings.cancel_untracked_orders)

            if assets is None:
                logger.warning("The inventory is unavailable, so this cycle leaves open buy orders alone.")
            else:
                await self._sync_open_to_bought(assets, buy_orders)

            await self._resolve_pending_listings(sell_listings, assets or {})
            await self._sync_listed_to_closed(sell_listings, assets or {})
            if settings.emergency_stop:
                logger.info("Trading is stopped, so nothing gets listed or bought this cycle.")
            else:
                if await self._list_bought_positions():
                    await self._attach_fresh_listings(assets or {})
                await self._open_new_positions()
        except SteamThrottled as e:
            logger.info(f"Steam is pacing us, this cycle does nothing: {e}")
        except Exception as e:
            logger.exception("Error in trading cycle")
            await self.action_log.record(
                ActionKind.CYCLE_FAILED,
                f"The trading cycle stopped early: {e!r}",
                level=ActionLevel.ERROR,
            )

        logger.info(f"Trading cycle complete in {time.monotonic() - start:.2f} s.")

    async def _snapshot_all_items(
        self,
    ) -> Optional[Dict[Tuple[str, str], Dict[str, List[Item]]]]:
        """
        Refresh the stored inventory for every game in the pool.

        None means Steam would not tell us what we own. That is not the same as owning
        nothing, and the difference decides whether a filled buy order looks cancelled.
        """
        pool_items: Sequence[PoolItem] = await self.pool_item_service.list()
        games: Dict[Tuple[str, str], List[PoolItem]] = {}
        for item in pool_items:
            games.setdefault((item.app_id, item.context_id), []).append(item)

        all_assets: Dict[Tuple[str, str], Dict[str, List[Item]]] = {}
        for app_id, ctx_id in games:
            try:
                all_assets[(app_id, ctx_id)] = await self.inventory_service.sync_snapshot(GameOptions(app_id, ctx_id))
            except Exception as e:
                logger.warning(f"Could not read the inventory for app {app_id}: {e!r}")
                return None
        return all_assets

    async def _reconcile_orders(self, buy_orders: list, sell_listings: list, cancel: bool) -> None:
        """Report Steam orders and listings that no active position accounts for."""
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
            await self.action_log.record(
                ActionKind.UNTRACKED_ORDER,
                f"Buy order {order_id} on Steam matches no active position"
                + (" and was cancelled." if cancel else "."),
                level=ActionLevel.WARNING,
                market_hash_name=order.get("item_name"),
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
            await self.action_log.record(
                ActionKind.UNTRACKED_ORDER,
                f"Sell listing {listing_id} on Steam matches no active position"
                + (" and was cancelled." if cancel else "."),
                level=ActionLevel.WARNING,
            )
            if cancel:
                await self.steam_service.cancel_sell_listing(listing_id)

    async def _sync_open_to_bought(
        self, assets: Dict[Tuple[str, str], Dict[str, List[Item]]], buy_orders: list
    ) -> None:
        """Resolve OPEN positions whose buy order is no longer active on Steam."""
        open_positions = await self.position_service.list_by_status(PositionStatus.OPEN)
        active_buy_order_ids = {order["order_id"] for order in buy_orders if "order_id" in order}
        claimed = await self._claimed_asset_ids()
        now = datetime.now(timezone.utc)

        for pos in open_positions:
            if pos.buy_order_id in active_buy_order_ids:
                continue

            status = await self._buy_order_status(pos)
            if status and status["active"] and not status["purchased"]:
                logger.info(f"Buy order {pos.buy_order_id} is still open on Steam, leaving position {pos.id} alone.")
                continue

            candidate = self._unclaimed_asset(assets, pos, claimed)

            if candidate:
                paid = status["paid"] if status else None
                logger.info(
                    f"Buy order {pos.buy_order_id} disappeared and item {candidate.id} acquired at "
                    f"{candidate.first_seen_at} was found for Position {pos.id}. Marking it as BOUGHT."
                )
                await self.position_service.mark_as_bought(
                    position_id=pos.id,
                    asset_id=candidate.id,
                    buy_price=paid,
                )
                await self.action_log.record(
                    ActionKind.POSITION_BOUGHT,
                    f"Bought at {paid or pos.buy_price}, asset {candidate.id}.",
                    market_hash_name=pos.pool_item_hash,
                    position_id=pos.id,
                )
                claimed.add(candidate.id)
                continue

            if status and not status["active"] and not status["purchased"]:
                logger.info(f"Steam reports buy order {pos.buy_order_id} was cancelled without filling.")
                await self.position_service.mark_as_cancelled(position_id=pos.id)
                await self.action_log.record(
                    ActionKind.POSITION_CANCELLED,
                    f"Steam reports buy order {pos.buy_order_id} was cancelled without filling.",
                    level=ActionLevel.WARNING,
                    market_hash_name=pos.pool_item_hash,
                    position_id=pos.id,
                )
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
            await self.action_log.record(
                ActionKind.POSITION_CANCELLED,
                f"Buy order {pos.buy_order_id} disappeared without a matching item.",
                level=ActionLevel.WARNING,
                market_hash_name=pos.pool_item_hash,
                position_id=pos.id,
            )

    async def _list_bought_positions(self) -> int:
        """Place a sell order for each BOUGHT position."""
        bought_positions = await self.position_service.list_by_status(PositionStatus.BOUGHT)
        floor = minimum_listing_price()
        listed = 0

        for pos in bought_positions:
            if pos.sell_price < floor:
                logger.warning(
                    f"Position {pos.id} asks {pos.sell_price} for {pos.pool_item_hash}, under the {floor} "
                    f"Steam accepts, so it stays unlisted."
                )
                await self.action_log.record(
                    ActionKind.SELL_ORDER_REFUSED,
                    f"{pos.sell_price} is below the {floor} Steam accepts, so nothing was listed.",
                    level=ActionLevel.WARNING,
                    market_hash_name=pos.pool_item_hash,
                    position_id=pos.id,
                )
                continue

            logger.info(
                f"Placing a sell order for Position {pos.id}, market_hash_name: {pos.pool_item_hash}, price: {pos.sell_price} rub."
            )
            try:
                await self.steam_service.create_sell_order(
                    asset_id=pos.asset_id,
                    game=GameOptions(pos.app_id, pos.context_id),
                    price=pos.sell_price,
                )
            except SellOrderFailed as e:
                logger.warning(f"Steam would not list position {pos.id}: {e}")
                await self.action_log.record(
                    ActionKind.SELL_ORDER_REFUSED,
                    f"Steam refused the listing at {pos.sell_price}: {e}",
                    level=ActionLevel.WARNING,
                    market_hash_name=pos.pool_item_hash,
                    position_id=pos.id,
                )
                continue

            await self.position_service.mark_as_listing_pending(position_id=pos.id)
            await self.action_log.record(
                ActionKind.SELL_ORDER_PLACED,
                f"Listed for sale at {pos.sell_price}.",
                market_hash_name=pos.pool_item_hash,
                position_id=pos.id,
            )
            listed += 1

        return listed

    async def _attach_fresh_listings(self, assets: Dict) -> None:
        """A listing placed this cycle is missing from the snapshot taken before it."""
        listings = await self.steam_service.get_my_market_listings()
        sell_listings = list(listings.get("sell_listings", {}).values())
        await self._resolve_pending_listings(sell_listings, assets, reconcile=False)

    @staticmethod
    def _listing_asset_id(listing: dict) -> Optional[str]:
        return (listing.get("description") or {}).get("id")

    @staticmethod
    def _unclaimed_asset(assets: Dict, position, claimed: set):
        """
        Steam issues a new asset id every time an item moves, so a stored one goes stale.

        Only an item that appeared after the position was opened can belong to it; anything
        older is the account owner's own copy.
        """
        key = (position.app_id, position.context_id)
        available = sorted(
            assets.get(key, {}).get(position.pool_item_hash, []),
            key=lambda item: item.first_seen_at,
        )
        taken = claimed - {position.asset_id}
        return next(
            (item for item in available if item.id not in taken and item.first_seen_at > position.created_at),
            None,
        )

    async def _buy_order_status(self, position) -> Optional[dict]:
        """Ask Steam what became of one buy order; a failure here must not stop the cycle."""
        try:
            return await self.steam_service.get_buy_order_status(
                buy_order_id=position.buy_order_id,
                market_hash_name=position.pool_item_hash,
                app_id=position.app_id,
            )
        except Exception as e:
            logger.warning(f"Could not read the status of buy order {position.buy_order_id}: {e!r}")
            return None

    async def _claimed_asset_ids(self) -> set:
        return {pos.asset_id for pos in await self.position_service.list() if pos.asset_id}

    async def _recover_cancelled_listing(self, position, assets: Dict, claimed: set) -> bool:
        """An item back in the inventory is proof the listing was cancelled, not sold."""
        candidate = self._unclaimed_asset(assets, position, claimed)
        if not candidate:
            return False

        logger.info(
            f"Position {position.id} has no listing but asset {candidate.id} is in the inventory. "
            f"Reverting it to BOUGHT so it gets listed again."
        )
        await self.position_service.revert_to_bought(position_id=position.id, asset_id=candidate.id)
        claimed.add(candidate.id)
        await self.action_log.record(
            ActionKind.LISTING_CANCELLED,
            f"Listing is gone and asset {candidate.id} is back in the inventory, so it will be listed again.",
            level=ActionLevel.WARNING,
            market_hash_name=position.pool_item_hash,
            position_id=position.id,
        )
        return True

    async def _resolve_pending_listings(self, listings: List, assets: Dict, reconcile: bool = True) -> None:
        """Attach the Steam listing id to LISTING_PENDING positions by matching on asset_id."""
        pending_positions = await self.position_service.list_by_status(PositionStatus.LISTING_PENDING)
        if not pending_positions:
            return

        asset_to_listing = {
            asset_id: li.get("listing_id")
            for li in listings
            if not li.get("need_confirmation") and (asset_id := self._listing_asset_id(li))
        }
        claimed = await self._claimed_asset_ids()

        for pos in pending_positions:
            listing_id = asset_to_listing.get(pos.asset_id)
            if not listing_id:
                if not reconcile:
                    continue
                if await self._close_sold_pending(pos):
                    continue
                if await self._recover_cancelled_listing(pos, assets, claimed):
                    continue
                logger.warning(f"Position {pos.id}: no active listing found yet for asset {pos.asset_id}.")
                continue

            logger.info(f"Position {pos.id}: resolved listing {listing_id} for asset {pos.asset_id}.")
            await self.position_service.mark_as_listed(position_id=pos.id, sell_order_id=listing_id)
            await self.action_log.record(
                ActionKind.LISTING_RESOLVED,
                f"Steam listing {listing_id} matched the position.",
                market_hash_name=pos.pool_item_hash,
                position_id=pos.id,
            )

    async def _close_sold_pending(self, position) -> bool:
        """A listing can sell before we ever learn its id, stranding the position in LISTING_PENDING."""
        history = await self._sold_listings()
        match = next(
            (
                (listing_id, sale)
                for listing_id, sale in history["sold"].items()
                if sale.get("asset_id") and sale["asset_id"] == position.asset_id
            ),
            None,
        )
        if not match:
            return False

        listing_id, sale = match
        logger.info(f"Position {position.id} sold as listing {listing_id} before its id reached us.")
        await self.position_service.mark_as_listed(position_id=position.id, sell_order_id=listing_id)
        closed = await self.position_service.close(
            position_id=position.id,
            sold_at=sale["sold_at"],
            net_proceeds=sale["net_proceeds"],
        )
        await self.action_log.record(
            ActionKind.POSITION_CLOSED,
            f"Sold at {closed.sell_price} as listing {listing_id}, received {closed.net_proceeds}, "
            f"profit {closed.realized_profit}.",
            market_hash_name=position.pool_item_hash,
            position_id=position.id,
        )
        return True

    async def _sold_listings(self) -> dict:
        """One market history read per cycle, shared by everything that needs it."""
        if self._sold_cache is None:
            self._sold_cache = await self.steam_service.get_sold_listings()
        return self._sold_cache

    async def _sync_listed_to_closed(
        self,
        listings: List,
        assets: Dict,
    ) -> None:
        """
        Close LISTED positions that Steam's own history confirms were sold.

        A listing missing from the response is not evidence of a sale: a failed fetch looks
        exactly the same and would book invented profit on every listed position at once.
        """
        listed_positions = await self.position_service.list_by_status(PositionStatus.LISTED)
        if not listed_positions:
            return

        history = await self._sold_listings()
        sold = history["sold"]
        active_listing_ids = {li.get("listing_id") for li in listings}
        claimed = await self._claimed_asset_ids()

        for pos in listed_positions:
            if not pos.sell_order_id:
                logger.warning(f"Position {pos.id} is LISTED without a listing id, skipping.")
                continue

            sale = sold.get(pos.sell_order_id)
            if sale:
                closed = await self.position_service.close(
                    position_id=pos.id,
                    sold_at=sale["sold_at"],
                    net_proceeds=sale["net_proceeds"],
                )
                logger.info(f"Steam history confirms listing {pos.sell_order_id} sold, closing position {pos.id}.")
                await self.action_log.record(
                    ActionKind.POSITION_CLOSED,
                    f"Sold at {closed.sell_price}, received {closed.net_proceeds}, "
                    f"profit {closed.realized_profit}.",
                    market_hash_name=pos.pool_item_hash,
                    position_id=pos.id,
                )
                continue

            if pos.sell_order_id not in active_listing_ids:
                if await self._recover_cancelled_listing(pos, assets, claimed):
                    continue
                await self._report_vanished_listing(pos, history["oldest_event_at"])

    async def _report_vanished_listing(self, pos, oldest_event_at) -> None:
        """The listing is neither on the market nor in the sale history, so leave it alone."""
        listed_at = getattr(pos, "listed_at", None)
        if oldest_event_at is not None and listed_at is not None and oldest_event_at > listed_at:
            reason = "the sale history does not reach back far enough to tell"
        else:
            reason = "Steam reports neither an active listing nor a sale"

        logger.warning(f"Listing {pos.sell_order_id} for position {pos.id} is unaccounted for: {reason}.")
        await self.action_log.record(
            ActionKind.LISTING_VANISHED,
            f"Listing {pos.sell_order_id} is gone but no sale is recorded: {reason}. Left as listed.",
            level=ActionLevel.WARNING,
            market_hash_name=pos.pool_item_hash,
            position_id=pos.id,
        )

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
            if item.max_listed - len(existing_positions) <= 0:
                continue

            if any(p.status == PositionStatus.OPEN for p in existing_positions):
                logger.info(
                    f"Skipping {item.market_hash_name}: it already has a buy order waiting, and Steam "
                    f"allows only one per item."
                )
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
                    f"{item.market_hash_name} is already selling at {lowest_ask}, below the {buy_price} "
                    f"we were ready to pay, so buying at that price instead."
                )
                buy_price = lowest_ask

            if buy_price > balance:
                logger.info(
                    f"Skipping {item.market_hash_name}: a single order of {buy_price} exceeds "
                    f"the wallet balance {balance}."
                )
                continue

            if buy_price > allowance:
                logger.info(
                    f"Skipping {item.market_hash_name}: {buy_price} exceeds the remaining buy order "
                    f"allowance {allowance}."
                )
                continue

            if buy_price > budget_left:
                logger.info(
                    f"Skipping {item.market_hash_name}: {buy_price} exceeds the remaining per item "
                    f"budget {budget_left}."
                )
                continue

            logger.info(
                f"Creating a buy order for {item.market_hash_name}, price: {buy_price} "
                f"(top bid {book['highest_buy_order']}, cheapest listing {lowest_ask})."
            )
            try:
                buy_id = await self.steam_service.create_buy_order(
                    market_hash_name=item.market_hash_name,
                    price=buy_price,
                    game=GameOptions(item.app_id, item.context_id),
                    quantity=1,
                )
            except BuyOrderFailed as e:
                logger.warning(f"Steam refused a buy order for {item.market_hash_name}: {e}")
                await self.action_log.record(
                    ActionKind.BUY_ORDER_REFUSED,
                    f"Steam refused a buy order at {buy_price}: {e}",
                    level=ActionLevel.WARNING,
                    market_hash_name=item.market_hash_name,
                )
                continue

            create = PositionCreate(
                pool_item_hash=item.market_hash_name,
                app_id=item.app_id,
                context_id=item.context_id,
                buy_order_id=buy_id,
                buy_price=buy_price,
                sell_price=item.effective_sell_price,
            )
            position = await self.position_service.add(create)
            await self.action_log.record(
                ActionKind.BUY_ORDER_PLACED,
                f"Placed a buy order at {buy_price} (cheapest listing {lowest_ask}).",
                market_hash_name=item.market_hash_name,
                position_id=position.id,
            )

            allowance -= buy_price
            free_slots -= 1
