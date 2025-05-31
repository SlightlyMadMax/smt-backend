import json

from fastapi import Depends
from steampy.client import SteamClient
from steampy.models import GameOptions

from smt.core.config import Settings, get_settings


class SteamService:
    def __init__(self, settings: Settings = Depends(get_settings)):
        self.client = SteamClient(api_key=settings.STEAM_API_KEY)
        self.client.login(
            username=settings.STEAM_USERNAME,
            password=settings.STEAM_PASSWORD,
            steam_guard=json.dumps(
                {
                    "steamid": settings.STEAMID,
                    "shared_secret": settings.STEAM_SHARED_SECRET,
                    "identity_secret": settings.STEAM_IDENTITY_SECRET,
                }
            ),
        )

    def get_inventory(self, game: GameOptions) -> dict:
        return self.client.get_my_inventory(game=game, count=1000)
