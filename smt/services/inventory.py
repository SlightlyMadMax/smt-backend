from smt.db.models import Item as ItemORM
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

    async def list(self, game_option):
        return await self.item_repo.list_for_game(game_option.app_id, game_option.context_id)

    async def refresh(self, game_option):
        raw_inventory = self.steam.get_inventory(game=game_option)
        orm_items: list[ItemORM] = []
        for raw in raw_inventory.values():
            data = transform_inventory_item(raw)
            orm_items.append(
                ItemORM(
                    id=data["id"],
                    app_id=game_option.app_id,
                    context_id=game_option.context_id,
                    name=data["name"],
                    market_hash_name=data["market_hash_name"],
                    tradable=data["tradable"],
                    marketable=data["marketable"],
                    amount=data["amount"],
                    icon_url=data["icon_url"],
                )
            )
        # replace all items for this game in the DB
        await self.item_repo.replace_for_game(orm_items)
