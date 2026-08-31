from typing import Dict, List, Sequence

from steampy.models import GameOptions

from smt.db.models import Item
from smt.repositories.items import ItemRepo
from smt.services.steam import SteamService
from smt.utils.steam import transform_inventory_item


class InventoryService:
    def __init__(
        self,
        steam: SteamService,
        item_repo: ItemRepo,
    ):
        self.steam = steam
        self.item_repo = item_repo

    async def list(self, game_option: GameOptions) -> Sequence[Item]:
        return await self.item_repo.list_by_game(game_option.app_id, game_option.context_id)

    async def get_by_id(self, asset_id: str) -> Item:
        return await self.item_repo.get_by_id(asset_id)

    def _to_orm(self, raw_inventory: dict, game_option: GameOptions) -> List[Item]:
        orm_items: List[Item] = []
        for raw in raw_inventory.values():
            data = transform_inventory_item(raw)
            orm_items.append(
                Item(
                    id=data["id"],
                    app_id=game_option.app_id,
                    context_id=game_option.context_id,
                    name=data["name"],
                    market_hash_name=data["market_hash_name"],
                    tradable=data["tradable"],
                    marketable=data["marketable"],
                    icon_url=data["icon_url"],
                )
            )
        return orm_items

    async def refresh(self, game_option: GameOptions) -> None:
        raw_inventory = await self.steam.get_inventory(game=game_option)
        await self.item_repo.sync_for_game(
            app_id=game_option.app_id,
            context_id=game_option.context_id,
            items=self._to_orm(raw_inventory, game_option),
        )

    async def sync_snapshot(self, game_option: GameOptions) -> Dict[str, List[Item]]:
        """
        Refresh the stored inventory from Steam and return it grouped by market_hash_name.

        The returned items are the persisted ones, so they carry `first_seen_at`.
        """
        await self.refresh(game_option)

        grouped: Dict[str, List[Item]] = {}
        for item in await self.list(game_option):
            grouped.setdefault(item.market_hash_name, []).append(item)
        return grouped
