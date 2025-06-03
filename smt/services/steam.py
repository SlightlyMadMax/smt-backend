import datetime
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

    def get_price_history(
        self, market_hash_name: str, app_id: str, days: int = 30
    ) -> list[tuple[datetime.datetime, float, int]]:
        resp = self.client.market.fetch_price_history(market_hash_name, app_id=app_id)
        raw = resp.get("prices", [])

        now = datetime.datetime.now(datetime.UTC)
        cutoff = now - datetime.timedelta(days=days)

        history: list[tuple[datetime, float, int]] = []
        for ts_str, price, volume in raw:
            t = datetime.datetime.strptime(ts_str, "%b %d %Y %H:%M")
            if t >= cutoff:
                history.append((t, float(price), int(volume)))

        print(history)

        return history
