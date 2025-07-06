import logging
from typing import Dict, List, Sequence, Tuple

from steampy.models import GameOptions

from smt.db.models import PoolItem
from smt.schemas.position import PositionCreate
from smt.services.inventory import InventoryService
from smt.services.pool import PoolService
from smt.services.position import PositionService
from smt.services.steam import SteamService


logger = logging.getLogger("services.trading")


class PositionTraderService:
    def __init__(
        self,
        steam_service: SteamService,
        inventory_service: InventoryService,
        position_service: PositionService,
        pool_item_service: PoolService,
    ):
        self.steam_service = steam_service
        self.inventory_service = inventory_service
        self.position_service = position_service
        self.pool_item_service = pool_item_service

    async def run_cycle(self) -> None:
        """Execute all steps of the trading cycle."""
        # Group and snapshot inventories once per game
        inventories = await self._snapshot_all_inventories()
        listings = self.steam_service.get_my_market_listings()

        logger.info("Starting trading cycle")
        try:
            await self._sync_open_to_bought(inventories)
            await self._sync_listed_to_closed(listings)
            await self._list_bought_positions()
            await self._open_new_positions(inventories)

        except Exception as e:
            logger.error(f"Error in trading cycle: {e}")

        logger.info("Trading cycle completed")

    async def _snapshot_all_inventories(self) -> Dict[Tuple[str, str], Dict[str, int]]:
        pool_items: Sequence[PoolItem] = await self.pool_item_service.list()
        games: Dict[Tuple[str, str], List[PoolItem]] = {}
        for item in pool_items:
            games.setdefault((item.app_id, item.context_id), []).append(item)

        inventories: Dict[Tuple[str, str], Dict[str, int]] = {}
        for (app_id, ctx_id), items in games.items():
            inventories[(app_id, ctx_id)] = await self.inventory_service.snapshot_counts(GameOptions(app_id, ctx_id))
        return inventories

    async def _sync_open_to_bought(
        self,
        inventories: Dict[Tuple[str, str], Dict[str, int]],
    ) -> None:
        """Mark OPEN positions as BOUGHT when buy orders fill."""
        open_positions = await self.position_service.list_open()
        for pos in open_positions:
            inv = inventories[(pos.pool_item.app_id, pos.pool_item.context_id)]
            if inv.get(pos.pool_item_hash, 0) >= pos.quantity:
                await self.position_service.mark_as_bought(position_id=pos.id)

    async def _sync_listed_to_closed(
        self,
        listings: List,
    ) -> None:
        """Mark LISTED positions as CLOSED when sell orders disappear."""
        listed_positions = await self.position_service.list_listed()
        for pos in listed_positions:
            still_active = any(li.order_id == pos.sell_order_id for li in listings)
            if not still_active:
                await self.position_service.close(position_id=pos.id)

    async def _list_bought_positions(self) -> None:
        """For newly marked BOUGHT positions, place sell orders."""
        bought_positions = await self.position_service.list_bought()
        for pos in bought_positions:
            sell_id = self.steam_service.create_sell_order(price=pos.sell_price)
            await self.position_service.mark_as_listed(position_id=pos.id, sell_order_id=sell_id)

    async def _open_new_positions(
        self,
        inventories: Dict[Tuple[str, str], Dict[str, int]],
    ) -> None:
        """Create new buy orders for PoolItems flagged for trading."""
        pool_items = await self.pool_item_service.list_marked_for_trading()

        # merge open and listed for existence check
        existing = await self.position_service.list_open()
        existing += await self.position_service.list_listed()

        for item in pool_items:
            inv = inventories[(item.app_id, item.context_id)]
            has_pos = any(p.pool_item_hash == item.market_hash_name for p in existing)
            if inv.get(item.market_hash_name, 0) == 0 and not has_pos:
                buy_id = self.steam_service.create_buy_order(
                    market_hash_name=item.market_hash_name,
                    price=item.effective_buy_price,
                    game=GameOptions(item.app_id, item.context_id),
                    quantity=item.max_listed,
                )
                create = PositionCreate(
                    pool_item_hash=item.market_hash_name,
                    buy_order_id=buy_id,
                    buy_price=item.effective_buy_price,
                    sell_price=item.effective_sell_price,
                    quantity=item.max_listed,
                )
                await self.position_service.add(create)
