from typing import List, Sequence

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
        return await self.item_repo.list_for_game(game_option.app_id, game_option.context_id)

    async def refresh(self, game_option: GameOptions) -> None:
        raw_inventory = self.steam.get_inventory(game=game_option)
        orm_items: list[Item] = []
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
        await self.item_repo.replace_for_game(
            app_id=game_option.app_id,
            context_id=game_option.context_id,
            items=orm_items,
        )

    async def snapshot_items(self, game_option: GameOptions) -> dict[str, List[Item]]:
        """
        Returns a mapping:
          market_hash_name -> list of Item
        """
        raw_inventory = self.steam.get_inventory(game=game_option)
        grouped: dict[str, list[Item]] = {}
        for raw in raw_inventory.values():
            data = transform_inventory_item(raw)
            item = Item(
                id=data["id"],
                app_id=game_option.app_id,
                context_id=game_option.context_id,
                name=data["name"],
                market_hash_name=data["market_hash_name"],
                tradable=data["tradable"],
                marketable=data["marketable"],
                icon_url=data["icon_url"],
            )
            grouped.setdefault(item.market_hash_name, []).append(item)
        return grouped

    async def snapshot_counts(self, game_option: GameOptions) -> dict[str, int]:
        raw_inventory = self.steam.get_inventory(game=game_option)
        counts: dict[str, int] = {}
        for raw in raw_inventory.values():
            mh = raw.get("market_hash_name")
            if not mh:
                continue
            counts[mh] = counts.get(mh, 0) + 1
        return counts
