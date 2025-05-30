from typing import List

from fastapi import APIRouter, Depends, Query

from smt.schemes.inventory import InventoryItem, GameName, GAME_MAP
from smt.services.steam import SteamService


router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("/", response_model=List[InventoryItem])
async def read_inventory(
    game: GameName = Query(..., description="Choose a supported game"),
    steam: SteamService = Depends(),
):
    game_option = GAME_MAP[game]
    inventory = steam.get_inventory(game=game_option)

    return [
        InventoryItem(
            id=data.get("assetid", assetid),
            name=data.get("name", ""),
            market_hash_name=data.get("market_hash_name", ""),
            tradable=int(data.get("tradable", 0)),
            marketable=int(data.get("marketable", 0)),
            amount=data.get("amount", "1"),
            icon_url=f"https://steamcommunity-a.akamaihd.net/economy/image/{data.get('icon_url', '')}",
        )
        for assetid, data in inventory.items()
    ]
