from typing import List

from fastapi import HTTPException, status
from sqlalchemy.exc import NoResultFound

from smt.db.models import Item
from smt.repositories.items import ItemRepo
from smt.repositories.pool_items import PoolRepo
from smt.schemas.pool import PoolItemCreate
from smt.schemas.stats import ItemStatCreate
from smt.services.stats import StatService
from smt.services.steam import SteamService


class PoolService:
    def __init__(
        self,
        item_repo: ItemRepo,
        pool_repo: PoolRepo,
        stat_service: StatService,
        steam: SteamService,
    ):
        self.item_repo = item_repo
        self.pool_repo = pool_repo
        self.stat_service = stat_service
        self.steam = steam

    async def list(self):
        return await self.pool_repo.list_items()

    async def add_one(self, asset_id: str):
        try:
            asset = await self.item_repo.get_by_id(asset_id)
        except NoResultFound:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Inventory item {asset_id} not found")

        payload = PoolItemCreate(
            market_hash_name=asset.market_hash_name,
            name=asset.name,
            icon_url=asset.icon_url,
        )
        await self.pool_repo.add_item(payload)

        # backfill history
        hist = self.steam.get_price_history(asset.market_hash_name, asset.app_id)
        stats = [
            ItemStatCreate(
                market_hash_name=asset.market_hash_name,
                recorded_at=ts,
                price=price,
                volume=vol,
            )
            for ts, price, vol in hist
        ]
        await self.stat_service.add_many(stats)

    async def add_many(self, asset_ids: List[str]):
        if not asset_ids:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "No asset IDs provided")

        assets_by_hash: dict[str, Item] = {}

        for aid in asset_ids:
            try:
                asset = await self.item_repo.get_by_id(aid)
                # Deduplicate by market_hash_name
                assets_by_hash.setdefault(asset.market_hash_name, asset)
            except NoResultFound:
                continue

        # Create pool items
        pool_items = [
            PoolItemCreate(
                market_hash_name=asset.market_hash_name,
                name=asset.name,
                icon_url=asset.icon_url,
            )
            for asset in assets_by_hash.values()
        ]
        await self.pool_repo.add_items(pool_items)

        # Backfill stats
        all_stats = []
        for asset in assets_by_hash.values():
            hist = self.steam.get_price_history(asset.market_hash_name, asset.app_id)
            stats = [
                ItemStatCreate(
                    market_hash_name=asset.market_hash_name,
                    recorded_at=ts,
                    price=price,
                    volume=vol,
                )
                for ts, price, vol in hist
            ]
            all_stats.extend(stats)

        await self.stat_service.add_many(all_stats)
