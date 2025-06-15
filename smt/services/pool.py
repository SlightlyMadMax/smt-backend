from typing import List, Sequence

from anyio import to_thread
from fastapi import HTTPException, status
from sqlalchemy.exc import NoResultFound
from steampy.models import GameOptions

from smt.db.models import Item, PoolItem
from smt.repositories.items import ItemRepo
from smt.repositories.pool_items import PoolRepo
from smt.schemas.pool import PoolItemCreate, PoolItemUpdate
from smt.schemas.price_history import PriceHistoryRecordCreate
from smt.services.price_history import PriceHistoryService
from smt.services.steam import SteamService


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

    async def get_many(self, names: List[str]) -> Sequence[PoolItem]:
        return await self.pool_repo.get_many(names)

    async def update(self, market_hash_name: str, payload: PoolItemUpdate) -> PoolItem:
        return await self.pool_repo.update(market_hash_name, payload)

    async def backfill_price_history_for(self, market_hash_names: List[str]) -> None:
        records: list[PriceHistoryRecordCreate] = []

        for market_hash_name in market_hash_names:
            try:
                pool_item = await self.pool_repo.get_by_market_hash_name(market_hash_name)
            except NoResultFound:
                continue

            game_opt = GameOptions(pool_item.app_id, pool_item.context_id)
            raw_hist = await to_thread.run_sync(
                self.steam.get_price_history,
                market_hash_name,
                game_opt,
            )
            for ts, price, vol in raw_hist:
                records.append(
                    PriceHistoryRecordCreate(
                        market_hash_name=market_hash_name,
                        recorded_at=ts,
                        price=price,
                        volume=vol,
                    )
                )

        if records:
            await self.price_history_service.add_many(records)

    async def update_snapshot_for(self, market_hash_name: str) -> None:
        try:
            pool_item = await self.pool_repo.get_by_market_hash_name(market_hash_name)
        except NoResultFound:
            return

        game_opt = GameOptions(pool_item.app_id, pool_item.context_id)
        snap = await to_thread.run_sync(
            self.steam.get_price,
            market_hash_name,
            game_opt,
        )
        update_payload = PoolItemUpdate(
            current_lowest_price=snap["lowest_price"],
            current_median_price=snap["median_price"],
            current_volume24h=snap["volume"],
        )
        await self.pool_repo.update(market_hash_name, update_payload)
