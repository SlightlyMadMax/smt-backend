from fastapi import APIRouter, Depends, Request
from fastapi.params import Query
from fastapi.templating import Jinja2Templates
from starlette.responses import HTMLResponse

from smt.schemas.inventory import GAME_MAP, GameName
from smt.services.dependencies import get_inventory_service, get_pool_service, get_settings_service
from smt.services.inventory import InventoryService
from smt.services.pool import PoolService
from smt.services.settings import SettingsService


router = APIRouter()

templates = Jinja2Templates(directory="/code/smt/templates")


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@router.get("/inventory", response_class=HTMLResponse, include_in_schema=False)
async def inventory_page(
    request: Request,
    game: GameName = Query(...),
    service: InventoryService = Depends(get_inventory_service),
):
    game_option = GAME_MAP[game]
    items = await service.list(game_option)
    return templates.TemplateResponse(
        "inventory.html",
        {
            "request": request,
            "items": items,
            "game": game.value,
        },
    )


@router.get("/pool", response_class=HTMLResponse, include_in_schema=False)
async def pool_page(
    request: Request,
    service: PoolService = Depends(get_pool_service),
):
    items = await service.list()
    return templates.TemplateResponse(
        "pool_items.html",
        {
            "request": request,
            "items": items,
        },
    )


@router.get("/settings", response_class=HTMLResponse, include_in_schema=False)
async def settings_page(
    request: Request,
    service: SettingsService = Depends(get_settings_service),
):
    settings = await service.get_settings()
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "settings": settings,
        },
    )
