import datetime
import json
from decimal import Decimal
from functools import wraps
from typing import Optional

import httpx
from anyio import to_thread
from steampy.client import SteamClient
from steampy.exceptions import LoginRequired
from steampy.models import Currency, GameOptions
from tenacity import AsyncRetrying, stop_after_attempt, wait_fixed

from smt.core.config import Settings
from smt.exceptions import BuyOrderFailed, OrderBookUnavailable, SellOrderFailed
from smt.logger import get_logger
from smt.utils.steam import calculate_fees, parse_steam_ts


logger = get_logger("services.steam")

STEAM_COMMUNITY_URL = "https://steamcommunity.com"
ORDER_BOOK_TIMEOUT = 30
ACCOUNT_CURRENCY = Currency.RUB


def _from_minor_units(value) -> Optional[Decimal]:
    """Steam quotes order book prices in minor units, e.g. 682 for 6.82 RUB."""
    return None if value is None else (Decimal(value) / 100).quantize(Decimal("0.01"))


def requires_login(func):
    @wraps(func)
    async def wrapper(self, *args, **kwargs):
        await self._ensure_login()
        return await func(self, *args, **kwargs)

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

    async def _ensure_login(self):
        async for attempt in AsyncRetrying(reraise=True, stop=stop_after_attempt(3), wait=wait_fixed(3)):
            with attempt:
                if not self._should_check_login():
                    return

                try:
                    await to_thread.run_sync(self.client.is_session_alive)
                except LoginRequired:
                    logger.info("Logging into Steam.")
                    await to_thread.run_sync(
                        self.client.login,
                        self._username,
                        self._password,
                        self._guard,
                    )
                    assert self.client.was_login_executed
                    logger.info("Steam login successful.")

                self._last_check = datetime.datetime.now(datetime.UTC)

    @requires_login
    async def get_inventory(self, game: GameOptions) -> dict:
        logger.debug(f"Fetching inventory for app_id = {game.app_id}.")
        return await to_thread.run_sync(self.client.get_my_inventory, game, True, 1000)

    @requires_login
    async def get_price_history(
        self, market_hash_name: str, game: GameOptions, days: int = 30
    ) -> list[tuple[datetime.datetime, Decimal, int]]:
        logger.debug(f"Fetching price history for {market_hash_name} (last {days}).")
        resp = await to_thread.run_sync(self.client.market.fetch_price_history, market_hash_name, game)
        raw = resp.get("prices", [])

        now = datetime.datetime.now(datetime.UTC)
        cutoff = now - datetime.timedelta(days=days)

        history: list[tuple[datetime.datetime, Decimal, int]] = []
        for ts_str, price, volume in raw:
            t = parse_steam_ts(ts_str)
            if t >= cutoff:
                history.append((t, Decimal(str(price)), int(volume)))

        return history

    @requires_login
    async def get_order_book(self, market_hash_name: str, app_id: str) -> dict:
        """
        Fetch the current order book for an item.

        The session cookies decide the currency: without them Steam answers in EUR
        instead of the wallet currency, so this must run authenticated.
        """
        logger.debug(f"Fetching order book for {market_hash_name}.")
        params = {"q": "Load", "qp": json.dumps([int(app_id), market_hash_name], separators=(",", ":"))}
        cookies = self.client._session.cookies.get_dict(domain="steamcommunity.com")

        try:
            async with httpx.AsyncClient(timeout=ORDER_BOOK_TIMEOUT) as client:
                resp = await client.get(f"{STEAM_COMMUNITY_URL}/market/orderbook", params=params, cookies=cookies)
            resp.raise_for_status()
            payload = resp.json().get("data") or {}
        except httpx.HTTPError as e:
            raise OrderBookUnavailable(f"Could not reach the order book for {market_hash_name}: {e}") from e
        if not payload.get("success"):
            raise OrderBookUnavailable(f"Steam returned no order book for {market_hash_name}")

        data = payload.get("data") or {}
        currency = data.get("eCurrency")
        if currency != ACCOUNT_CURRENCY:
            raise OrderBookUnavailable(
                f"Order book for {market_hash_name} is priced in currency {currency}, expected {ACCOUNT_CURRENCY}"
            )

        return {
            "lowest_sell_order": _from_minor_units(data.get("amtMinSellOrder")),
            "highest_buy_order": _from_minor_units(data.get("amtMaxBuyOrder")),
            "sell_order_count": data.get("cSellOrders"),
            "buy_order_count": data.get("cBuyOrders"),
        }

    @requires_login
    async def get_my_market_listings(self) -> dict:
        logger.debug("Fetching market listings.")
        return await to_thread.run_sync(self.client.market.get_my_market_listings)

    @requires_login
    async def create_buy_order(self, market_hash_name: str, price: Decimal, game: GameOptions, quantity: int) -> str:
        logger.debug(f"Creating a buy order for {quantity} {market_hash_name}.")
        kopecks = int((price * 100).to_integral_value())
        resp = await to_thread.run_sync(
            self.client.market.create_buy_order,
            market_hash_name,
            str(kopecks),
            quantity,
            game,
            ACCOUNT_CURRENCY,
        )
        if not resp.get("success", False):
            logger.error(f"Failed to create a buy order for {quantity} {market_hash_name}. Response: {resp}")
            raise BuyOrderFailed(f"Steam rejected the buy order for {market_hash_name}: {resp}")
        buy_order_id = resp.get("buy_orderid")
        logger.info(f"Buy order with id {buy_order_id} successfully created.")
        return buy_order_id

    @requires_login
    async def create_sell_order(self, asset_id: str, game: GameOptions, price: Decimal) -> None:
        logger.debug(f"Creating a sell order for {asset_id} at {price} rub.")
        kopecks = int((price * 100).to_integral_value())
        net_received = str(calculate_fees(gross=kopecks)["net_received"])
        resp = await to_thread.run_sync(self.client.market.create_sell_order, asset_id, game, net_received)
        if not resp.get("success", False):
            logger.error(f"Failed to create a sell order for {asset_id} at {price} rub. Response: {resp}")
            raise SellOrderFailed(f"Steam rejected the sell order for {asset_id}: {resp}")
        logger.info(f"Sell order for {asset_id} accepted by Steam. Response: {resp}")
