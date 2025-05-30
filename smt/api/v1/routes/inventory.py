from fastapi import APIRouter, Depends

from smt.core.config import Settings, get_settings


router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("/debug-settings")
def show_settings(settings: Settings = Depends(get_settings)):
    return {"user": settings.STEAM_USERNAME}
