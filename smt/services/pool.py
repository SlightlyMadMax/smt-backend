from typing import List, Sequence

from fastapi import HTTPException, status
from sqlalchemy.exc import NoResultFound

from smt.db.models import Item, PoolItem
from smt.repositories.items import ItemRepo
from smt.repositories.pool_items import PoolRepo
from smt.schemas.pool import PoolItemCreate, PoolItemUpdate


class PoolService:
    def __init__(
        self,
        item_repo: ItemRepo,
        pool_repo: PoolRepo,
    ):
        self.item_repo = item_repo
        self.pool_repo = pool_repo

    async def list(self) -> Sequence[PoolItem]:
        return await self.pool_repo.list_items()

    async def add_one(self, asset_id: str) -> PoolItem:
        try:
            asset = await self.item_repo.get_by_id(asset_id)
        except NoResultFound:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Inventory item {asset_id} not found")

        payload = PoolItemCreate(
            market_hash_name=asset.market_hash_name,
            name=asset.name,
            icon_url=asset.icon_url,
            app_id=asset.app_id,
            context_id=asset.context_id,
        )
        return await self.pool_repo.add_item(payload)

    async def add_many(self, asset_ids: List[str]) -> List[PoolItem]:
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

    async def get_many(self, market_hash_names: List[str]) -> Sequence[PoolItem]:
        return await self.pool_repo.get_many(market_hash_names)

    async def update(self, market_hash_name: str, payload: PoolItemUpdate) -> PoolItem:
        return await self.pool_repo.update(market_hash_name, payload)

    async def remove(self, market_hash_name: str) -> bool:
        return await self.pool_repo.remove(market_hash_name)

    async def remove_many(self, market_hash_names: List[str]) -> int:
        return await self.pool_repo.remove_many(market_hash_names)
