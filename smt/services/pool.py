from typing import List, Sequence

from fastapi import HTTPException, status
from sqlalchemy.exc import NoResultFound

from smt.db.models import Item, PoolItem
from smt.repositories.pool_items import PoolRepo
from smt.schemas.pool import PoolItemCreate, PoolItemUpdate
from smt.services.inventory import InventoryService


class PoolService:
    def __init__(
        self,
        pool_repo: PoolRepo,
        inventory_service: InventoryService,
    ):
        self.pool_repo = pool_repo
        self.inventory_service = inventory_service

    async def list(self) -> Sequence[PoolItem]:
        return await self.pool_repo.list()

    async def list_marked_for_trading(self) -> Sequence[PoolItem]:
        return await self.pool_repo.list_marked_for_trading()

    async def summary(self) -> dict:
        items = await self.pool_repo.list()
        ready = sum(1 for item in items if item.use_for_trading)
        return {"total": len(items), "ready": ready, "not_ready": len(items) - ready}

    async def get_by_market_hash_name(self, market_hash_name: str) -> PoolItem:
        return await self.pool_repo.get_by_market_hash_name(market_hash_name)

    async def add(self, asset_id: str) -> PoolItem:
        try:
            asset = await self.inventory_service.get_by_id(asset_id)
        except NoResultFound:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Inventory item {asset_id} not found")

        payload = PoolItemCreate(
            market_hash_name=asset.market_hash_name,
            name=asset.name,
            icon_url=asset.icon_url,
            app_id=asset.app_id,
            context_id=asset.context_id,
        )
        created = await self.pool_repo.add(payload)
        if created is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{asset.market_hash_name} is already in the pool",
            )
        return created

    async def add_unowned(self, items: List[PoolItemCreate]) -> List[PoolItem]:
        """
        Put items in the pool straight from a market scan.

        Everything else here starts from the inventory, which means an item has to be
        bought by hand before the bot may trade it. A scan knows nothing about ownership.
        """
        if not items:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "No items provided")

        unique = {item.market_hash_name: item for item in items}
        return await self.pool_repo.add_many(list(unique.values()))

    async def add_many(self, asset_ids: List[str]) -> List[PoolItem]:
        if not asset_ids:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "No asset IDs provided")

        # dedupe by market_hash_name
        unique_assets: dict[str, Item] = {}
        for aid in asset_ids:
            try:
                asset = await self.inventory_service.get_by_id(aid)
            except NoResultFound:
                continue
            unique_assets[asset.market_hash_name] = asset

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
        return await self.pool_repo.add_many(pool_items)

    async def get_many(self, market_hash_names: List[str]) -> Sequence[PoolItem]:
        return await self.pool_repo.get_many(market_hash_names)

    async def update(self, market_hash_name: str, payload: PoolItemUpdate) -> PoolItem:
        return await self.pool_repo.update(market_hash_name, payload)

    async def delete(self, market_hash_name: str) -> bool:
        return await self.pool_repo.delete(market_hash_name)

    async def delete_many(self, market_hash_names: List[str]) -> int:
        return await self.pool_repo.delete_many(market_hash_names)
