from fastapi import APIRouter, Depends, Query
from starlette.responses import RedirectResponse

from smt.db.models import Item as ItemORM
from smt.repositories.dependencies import get_item_repo
from smt.repositories.items import ItemRepo
from smt.schemas.inventory import GAME_MAP, GameName, InventoryItem
from smt.services.steam import SteamService
from smt.utils.steam import transform_inventory_item


router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("/", response_model=list[InventoryItem])
async def read_inventory(
    game: GameName = Query(..., description="Choose a supported game"),
    repo: ItemRepo = Depends(get_item_repo),
):
    game_option = GAME_MAP[game]
    return await repo.list_for_game(game_option.app_id, game_option.context_id)


@router.put("/refresh", response_class=RedirectResponse)
async def refresh_inventory(
    game: GameName = Query(...),
    steam: SteamService = Depends(),
    repo: ItemRepo = Depends(get_item_repo),
):
    game_option = GAME_MAP[game]
    raw_inventory = steam.get_inventory(game=game_option)

    orm_items: list[ItemORM] = []
    for raw_data in raw_inventory.values():
        data = transform_inventory_item(raw_data)
        orm_items.append(
            ItemORM(
                id=data["id"],
                app_id=game_option.app_id,
                context_id=game_option.context_id,
                name=data["name"],
                market_hash_name=data["market_hash_name"],
                tradable=bool(data["tradable"]),
                marketable=bool(data["marketable"]),
                amount=int(data["amount"]),
                icon_url=data["icon_url"],
            )
        )

    await repo.replace_for_game(orm_items)

    return RedirectResponse(url=f"/inventory?game={game.value}", status_code=303)
