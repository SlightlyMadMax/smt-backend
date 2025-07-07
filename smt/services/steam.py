import datetime
import json
from decimal import Decimal
from functools import wraps
from typing import Optional

from steampy.client import SteamClient
from steampy.exceptions import LoginRequired
from steampy.models import Currency, GameOptions
from tenacity import retry, stop_after_attempt, wait_fixed

from smt.core.config import Settings
from smt.logger import get_logger
from smt.utils.steam import calculate_fees, parse_steam_ts


logger = get_logger("services.steam")


def requires_login(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        self._ensure_login()
        return func(self, *args, **kwargs)

    return wrapper


class SteamService:
    def __init__(self, settings: Settings):
        self.client = SteamClient(api_key=settings.STEAM_API_KEY)
        self._username: str = settings.STEAM_USERNAME
        self._password: str = settings.STEAM_PASSWORD
        self._guard: str = json.dumps(
            {
                "steamid": settings.STEAMID,
                "shared_secret": settings.STEAM_SHARED_SECRET,
                "identity_secret": settings.STEAM_IDENTITY_SECRET,
            }
        )
        self._last_check: Optional[datetime] = None
        self._check_interval = datetime.timedelta(minutes=5)

    def _should_check_login(self) -> bool:
        return not self._last_check or datetime.datetime.now(datetime.UTC) - self._last_check > self._check_interval

    @retry(reraise=True, stop=stop_after_attempt(3), wait=wait_fixed(3))
    def _ensure_login(self):
        if not self._should_check_login():
            return

        try:
            self.client.is_session_alive()
        except LoginRequired:
            logger.info("Logging into Steam.")
            self.client.login(
                username=self._username,
                password=self._password,
                steam_guard=self._guard,
            )
            assert self.client.was_login_executed

        self._last_check = datetime.datetime.now(datetime.UTC)

    @requires_login
    def get_inventory(self, game: GameOptions) -> dict:
        logger.debug(f"Fetching inventory for app_id = {game.app_id}.")
        return self.client.get_my_inventory(game=game, count=1000)

    @requires_login
    def get_price_history(
        self, market_hash_name: str, game: GameOptions, days: int = 30
    ) -> list[tuple[datetime.datetime, float, int]]:
        logger.debug(f"Fetching price history for {market_hash_name} (last {days}).")
        resp = self.client.market.fetch_price_history(market_hash_name, game=game)
        raw = resp.get("prices", [])

        now = datetime.datetime.now(datetime.UTC)
        cutoff = now - datetime.timedelta(days=days)

        history: list[tuple[datetime, float, int]] = []
        for ts_str, price, volume in raw:
            t = parse_steam_ts(ts_str)
            if t >= cutoff:
                history.append((t, float(price), int(volume)))

        return history

    @requires_login
    def get_price(self, market_hash_name: str, game: GameOptions) -> dict:
        logger.debug(f"Fetching current price and volume for {market_hash_name}.")
        resp = self.client.market.fetch_price(market_hash_name, game=game, currency=Currency.RUB, country="RU")
        return resp

    @requires_login
    def create_buy_order(self, market_hash_name: str, price: Decimal, game: GameOptions, quantity: int) -> str:
        logger.debug(f"Creating a buy order for {quantity} {market_hash_name}.")
        kopecks = int((price * 100).to_integral_value())
        resp = self.client.market.create_buy_order(
            market_name=market_hash_name,
            price_single_item=str(kopecks),
            quantity=quantity,
            game=game,
            currency=Currency.RUB,
        )
        if not resp.get("success", False):
            logger.error(f"Failed to create a buy order for {quantity} {market_hash_name}.")
            raise Exception
        buy_order_id = resp.get("buy_orderid")
        logger.info(f"Buy order with id {buy_order_id} successfully created.")
        return buy_order_id

    @requires_login
    def create_sell_order(self, asset_id: str, game: GameOptions, price: Decimal) -> str:
        logger.debug(f"Creating a sell order for {asset_id} at {price} rub.")
        kopecks = int((price * 100).to_integral_value())
        net_received = calculate_fees(gross=kopecks)["net_received"]
        resp = self.client.market.create_sell_order(assetid=asset_id, game=game, money_to_receive=net_received)
        if not resp.get("success", False):
            logger.error(f"Failed to create a sell order for {asset_id} at {price} rub.")
            raise Exception
        sell_order_id = resp.get("sell_orderid")
        logger.info(f"Sell order with id {sell_order_id} successfully created.")
        return sell_order_id
