from typing import List

from fastapi import HTTPException, status
from sqlalchemy.exc import NoResultFound

from smt.repositories.items import ItemRepo
from smt.repositories.pool_items import PoolRepo
from smt.repositories.stats import StatRepo
from smt.schemas.pool import PoolItemCreate
from smt.schemas.stats import ItemStatCreate
from smt.services.steam import SteamService


class PoolService:
    def __init__(
        self,
        item_repo: ItemRepo,
        pool_repo: PoolRepo,
        stat_repo: StatRepo,
        steam: SteamService,
    ):
        self.item_repo = item_repo
        self.pool_repo = pool_repo
        self.stat_repo = stat_repo
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
        await self.stat_repo.add_stats(stats)

    async def add_many(self, asset_ids: List[str]):
        if not asset_ids:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "No asset IDs provided")

        payloads: list[PoolItemCreate] = []
        for aid in asset_ids:
            try:
                asset = await self.item_repo.get_by_id(aid)
                payloads.append(
                    PoolItemCreate(
                        market_hash_name=asset.market_hash_name,
                        name=asset.name,
                        icon_url=asset.icon_url,
                    )
                )
            except NoResultFound:
                continue

        # deduplicate by market_hash_name
        unique_payloads: dict[str, PoolItemCreate] = {}
        for p in payloads:
            unique_payloads.setdefault(p.market_hash_name, p)

        await self.pool_repo.add_items(list(unique_payloads.values()))
