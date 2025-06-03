import datetime
import json
from functools import wraps

from fastapi import Depends
from steampy.client import SteamClient
from steampy.models import GameOptions

from smt.core.config import Settings, get_settings


def requires_login(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        self._ensure_login()
        return func(self, *args, **kwargs)

    return wrapper


class SteamService:
    def __init__(self, settings: Settings = Depends(get_settings)):
        self.client = SteamClient(api_key=settings.STEAM_API_KEY)
        self._logged_in = False
        self._username = settings.STEAM_USERNAME
        self._password = settings.STEAM_PASSWORD
        self._guard = json.dumps(
            {
                "steamid": settings.STEAMID,
                "shared_secret": settings.STEAM_SHARED_SECRET,
                "identity_secret": settings.STEAM_IDENTITY_SECRET,
            }
        )

    def _ensure_login(self):
        if not self._logged_in:
            self.client.login(
                username=self._username,
                password=self._password,
                steam_guard=self._guard,
            )
            self._logged_in = True

    @requires_login
    def get_inventory(self, game: GameOptions) -> dict:
        return self.client.get_my_inventory(game=game, count=1000)

    @requires_login
    def get_price_history(
        self, market_hash_name: str, game: GameOptions, days: int = 30
    ) -> list[tuple[datetime.datetime, float, int]]:
        resp = self.client.market.fetch_price_history(market_hash_name, game=game)
        raw = resp.get("prices", [])

        now = datetime.datetime.now(datetime.UTC)
        cutoff = now - datetime.timedelta(days=days)

        history: list[tuple[datetime, float, int]] = []
        for ts_str, price, volume in raw:
            t = datetime.datetime.strptime(ts_str, "%b %d %Y %H:%M")
            if t >= cutoff:
                history.append((t, float(price), int(volume)))

        return history
