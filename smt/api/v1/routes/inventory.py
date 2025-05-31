from typing import List

from fastapi import APIRouter, Depends, Query

from smt.schemes.inventory import GAME_MAP, GameName, InventoryItem
from smt.services.steam import SteamService
from smt.utils.steam import transform_inventory_item


router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("/", response_model=List[InventoryItem])
async def read_inventory(
    game: GameName = Query(..., description="Choose a supported game"),
    steam: SteamService = Depends(),
):
    game_option = GAME_MAP[game]
    raw_inventory = steam.get_inventory(game=game_option)
    items = [transform_inventory_item(item) for item in raw_inventory.values()]
    return items


@router.put("/update-inventory")
async def update_inventory(game: GameName = Query(...), steam: SteamService = Depends()):
    game_option = GAME_MAP[game]
    raw_inventory = steam.get_inventory(game=game_option)
    items = [transform_inventory_item(item) for item in raw_inventory.values()]

    # await save_inventory_cache(game_option.app_id, items)
    return {"message": "Inventory updated", "count": len(items)}
