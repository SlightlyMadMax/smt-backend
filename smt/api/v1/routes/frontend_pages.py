from fastapi import APIRouter, Request, Depends
from fastapi.params import Query
from fastapi.templating import Jinja2Templates
from starlette.responses import HTMLResponse

from smt.schemes.inventory import GameName, GAME_MAP
from smt.services.steam import SteamService
from smt.utils.steam import transform_inventory_item

router = APIRouter()

templates = Jinja2Templates(directory="/code/smt/templates")


@router.get("/")
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@router.get("/inventory", response_class=HTMLResponse)
async def inventory_page(
    request: Request, game: GameName = Query(...), steam: SteamService = Depends()
):
    game_option = GAME_MAP[game]
    # cached = await get_cached_inventory(game_option.app_id)
    cached = False
    if cached:
        items = cached
    else:
        raw_inventory = steam.get_inventory(game=game_option)
        items = [transform_inventory_item(item) for item in raw_inventory.values()]

    return templates.TemplateResponse(
        "inventory.html",
        {
            "request": request,
            "items": items,
            "game": game,
        },
    )
