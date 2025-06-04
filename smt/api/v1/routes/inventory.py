from fastapi import APIRouter, Depends, Query

from smt.schemas.inventory import GAME_MAP, GameName, InventoryItem
from smt.services.dependencies import get_inventory_service
from smt.services.inventory import InventoryService


router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("/", response_model=list[InventoryItem])
async def read_inventory(
    game: GameName = Query(...),
    service: InventoryService = Depends(get_inventory_service),
):
    game_option = GAME_MAP[game]
    return await service.list(game_option)


@router.put("/refresh")
async def refresh_inventory(
    game: GameName = Query(...),
    service: InventoryService = Depends(get_inventory_service),
):
    game_option = GAME_MAP[game]
    await service.refresh(game_option)
