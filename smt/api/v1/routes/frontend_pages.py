from fastapi import APIRouter, Depends, Request
from fastapi.params import Query
from fastapi.templating import Jinja2Templates
from starlette.responses import HTMLResponse

from smt.repositories.dependencies import get_item_repo
from smt.repositories.items import ItemRepo
from smt.schemes.inventory import GAME_MAP, GameName


router = APIRouter()

templates = Jinja2Templates(directory="/code/smt/templates")


@router.get("/")
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@router.get("/inventory", response_class=HTMLResponse)
async def inventory_page(
    request: Request,
    game: GameName = Query(...),
    repo: ItemRepo = Depends(get_item_repo),
):
    game_option = GAME_MAP[game]
    items = await repo.list_for_game(game_option.app_id, game_option.context_id)
    return templates.TemplateResponse(
        "inventory.html",
        {
            "request": request,
            "items": items,
            "game": game,
        },
    )
