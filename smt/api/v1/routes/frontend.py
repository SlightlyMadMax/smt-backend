from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates


frontend_router = APIRouter()

templates = Jinja2Templates(directory="/code/smt/templates")


@frontend_router.get("/")
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})
