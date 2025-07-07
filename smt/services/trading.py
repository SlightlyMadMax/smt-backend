import logging
from typing import Dict, List, Sequence, Tuple

from steampy.models import GameOptions

from smt.db.models import PoolItem
from smt.schemas.position import PositionCreate, PositionStatus
from smt.services.inventory import InventoryService
from smt.services.pool import PoolService
from smt.services.position import PositionService
from smt.services.settings import SettingsService
from smt.services.steam import SteamService


logger = logging.getLogger("services.trading")


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
        try:
            assets = await self._snapshot_all_items()
            await self._sync_open_to_bought(assets)

            await self._list_bought_positions()

            listings = self.steam_service.get_my_market_listings()
            await self._sync_listed_to_closed(listings)

            settings = await self.settings_service.get_settings()
            if not settings.emergency_stop:
                await self._open_new_positions(assets)
        except Exception as e:
            logger.error(f"Error in trading cycle: {e}")

        logger.info("Trading cycle completed")

    async def _snapshot_all_items(
        self,
    ) -> Dict[Tuple[str, str], Dict[str, List[str]]]:
        """
        Returns a mapping per game:
          (app_id, context_id) -> { market_hash_name: [asset_id, ...] }
        """
        pool_items: Sequence[PoolItem] = await self.pool_item_service.list()
        games: Dict[Tuple[str, str], List[PoolItem]] = {}
        for item in pool_items:
            games.setdefault((item.app_id, item.context_id), []).append(item)

        all_assets: Dict[Tuple[str, str], Dict[str, List[str]]] = {}
        for (app_id, ctx_id), items in games.items():
            # snapshot_items returns {market_hash_name: [ItemORM, ...]}
            grouped = await self.inventory_service.snapshot_items(GameOptions(app_id, ctx_id))
            # reduce to asset_id list
            all_assets[(app_id, ctx_id)] = {mh: [itm.id for itm in lst] for mh, lst in grouped.items()}
        return all_assets

    async def _sync_open_to_bought(self, assets: Dict[Tuple[str, str], Dict[str, List[str]]]) -> None:
        """Assign asset_id to OPEN positions when buys fill."""
        open_positions = await self.position_service.list_by_status(PositionStatus.OPEN)
        # build set of already claimed asset_ids
        claimed = {pos.asset_id for pos in await self.position_service.list() if pos.asset_id}

        for pos in open_positions:
            key = (pos.pool_item.app_id, pos.pool_item.context_id)
            available = assets.get(key, {}).get(pos.pool_item_hash, [])
            # find first unclaimed asset
            candidate = next((aid for aid in available if aid not in claimed), None)
            if candidate:
                logger.info(
                    f"Found an unclaimed item with id = {candidate} for Position {pos.id}, marking the Position as BOUGHT."
                )
                # record asset_id and mark BOUGHT
                await self.position_service.mark_as_bought(
                    position_id=pos.id,
                    asset_id=candidate,
                )
                claimed.add(candidate)

    async def _list_bought_positions(self) -> None:
        """Place a sell order for each BOUGHT position."""
        bought_positions = await self.position_service.list_by_status(PositionStatus.BOUGHT)
        for pos in bought_positions:
            logger.info(
                f"Placing a sell order for Position {pos.id}, market_hash_name: {pos.pool_item_hash}, price: {pos.sell_price} rub."
            )
            sell_id = self.steam_service.create_sell_order(
                asset_id=pos.asset_id,
                game=GameOptions(pos.pool_item.app_id, pos.pool_item.context_id),
                price=pos.sell_price,
            )
            await self.position_service.mark_as_listed(
                position_id=pos.id,
                sell_order_id=sell_id,
            )

    async def _sync_listed_to_closed(
        self,
        listings: List,
    ) -> None:
        """Mark LISTED positions as CLOSED when sell orders disappear."""
        listed_positions = await self.position_service.list_by_status(PositionStatus.LISTED)
        for pos in listed_positions:
            still_active = any(li.order_id == pos.sell_order_id for li in listings)
            if not still_active:
                logger.info(f"Sell order {pos.sell_order_id} for Position {pos.id} disappeared, closing position.")
                await self.position_service.close(position_id=pos.id)

    async def _open_new_positions(
        self,
        assets: Dict[Tuple[str, str], Dict[str, List[str]]],
    ) -> None:
        """Submit new buy orders for PoolItems flagged for trading if none are open."""
        pool_items = await self.pool_item_service.list_marked_for_trading()
        existing = await self.position_service.list_active()

        for item in pool_items:
            key = (item.app_id, item.context_id)
            held_asset_ids = assets.get(key, {}).get(item.market_hash_name, [])

            existing_positions = [p for p in existing if p.pool_item_hash == item.market_hash_name]
            current_count = len(existing_positions) + len(held_asset_ids)
            to_create = item.max_listed - current_count
            if to_create <= 0:
                continue

            for _ in range(to_create):
                logger.info(f"Creating a buy order for {item.market_hash_name}, price: {item.effective_buy_price}.")
                buy_id = self.steam_service.create_buy_order(
                    market_hash_name=item.market_hash_name,
                    price=item.effective_buy_price,
                    game=GameOptions(item.app_id, item.context_id),
                    quantity=1,
                )
                create = PositionCreate(
                    pool_item_hash=item.market_hash_name,
                    buy_order_id=buy_id,
                    buy_price=item.effective_buy_price,
                    sell_price=item.effective_sell_price,
                )
                await self.position_service.add(create)
