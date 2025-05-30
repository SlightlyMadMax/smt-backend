from fastapi import Depends

from smt.core.config import Settings, get_settings
from smt.services.steam import SteamService


def get_steam_service(
    settings: Settings = Depends(get_settings),
) -> SteamService:
    return SteamService(settings)
