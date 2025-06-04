from typing import List, Sequence

from fastapi import HTTPException, status
from sqlalchemy.exc import NoResultFound

from smt.db.models import Item, PoolItem
from smt.repositories.items import ItemRepo
from smt.repositories.pool_items import PoolRepo
from smt.schemas.pool import PoolItemCreate, PoolItemUpdate
from smt.services.price_history import PriceHistoryService
from smt.services.steam import SteamService
from smt.tasks.price_history import backfill_price_history_batch, update_pool_item_snapshot


class PoolService:
    def __init__(
        self,
        item_repo: ItemRepo,
        pool_repo: PoolRepo,
        price_history_service: PriceHistoryService,
        steam: SteamService,
    ):
        self.item_repo = item_repo
        self.pool_repo = pool_repo
        self.price_history_service = price_history_service
        self.steam = steam

    async def list(self) -> Sequence[PoolItem]:
        return await self.pool_repo.list_items()

    async def add_one(self, asset_id: str) -> bool:
        try:
            asset = await self.item_repo.get_by_id(asset_id)
        except NoResultFound:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Inventory item {asset_id} not found")

        backfill_price_history_batch.delay([asset.market_hash_name])
        update_pool_item_snapshot.delay(asset.market_hash_name)

        payload = PoolItemCreate(
            market_hash_name=asset.market_hash_name,
            name=asset.name,
            icon_url=asset.icon_url,
            app_id=asset.app_id,
            context_id=asset.context_id,
        )
        return await self.pool_repo.add_item(payload)

    async def add_many(self, asset_ids: List[str]) -> int:
        if not asset_ids:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "No asset IDs provided")

        # dedupe by market_hash_name
        unique_assets: dict[str, Item] = {}
        for aid in asset_ids:
            try:
                asset = await self.item_repo.get_by_id(aid)
            except NoResultFound:
                continue
            unique_assets[asset.market_hash_name] = asset

        backfill_price_history_batch.delay(list(unique_assets.keys()))
        for market_hash_name in unique_assets.keys():
            update_pool_item_snapshot.delay(market_hash_name)

        # Create pool items
        pool_items = [
            PoolItemCreate(
                market_hash_name=asset.market_hash_name,
                name=asset.name,
                icon_url=asset.icon_url,
                app_id=asset.app_id,
                context_id=asset.context_id,
            )
            for asset in unique_assets.values()
        ]
        return await self.pool_repo.add_items(pool_items)

    async def update(self, market_hash_name: str, payload: PoolItemUpdate) -> bool:
        return await self.pool_repo.update(market_hash_name, payload)
