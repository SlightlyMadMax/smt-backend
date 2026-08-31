import asyncio
import datetime
import json
import time
import uuid
from contextlib import asynccontextmanager
from decimal import Decimal
from functools import partial, wraps
from typing import Optional

import httpx
from anyio import to_thread
from redis.asyncio import Redis
from steampy.client import SteamClient
from steampy.models import Currency, GameOptions

from smt.core.config import Settings
from smt.exceptions import BuyOrderFailed, OrderBookUnavailable, SellOrderFailed, SteamLoginUnavailable
from smt.logger import get_logger
from smt.utils.rate_limit import RedisRateLimiter
from smt.utils.steam import calculate_fees, parse_steam_ts


logger = get_logger("services.steam")

STEAM_COMMUNITY_URL = "https://steamcommunity.com"
ORDER_BOOK_TIMEOUT = 30
ACCOUNT_CURRENCY = Currency.RUB
RATE_LIMIT_KEY = "smt:steam:calls"
LOGIN_BLOCK_KEY = "smt:steam:login_block"
LOGIN_FAILURES_KEY = "smt:steam:login_failures"
LOGIN_LOCK_KEY = "smt:steam:login_lock"
SESSION_KEY = "smt:steam:session"
LOGIN_LOCK_TTL = 60
LOGIN_LOCK_WAIT = 90
SESSION_TTL = 60 * 60 * 12
STEAM_MAX_CALLS_PER_PERIOD = 15
STEAM_RATE_LIMIT_PERIOD = 60.0
LOGIN_COOLDOWN_BASE = datetime.timedelta(minutes=5)
LOGIN_COOLDOWN_MAX = datetime.timedelta(hours=1)


def _from_minor_units(value) -> Optional[Decimal]:
    """Steam quotes order book prices in minor units, e.g. 682 for 6.82 RUB."""
    return None if value is None else (Decimal(value) / 100).quantize(Decimal("0.01"))


def _to_levels(compact: Optional[list]) -> list[dict]:
    """Steam sends the depth as a flat [price, quantity, price, quantity, ...] list."""
    if not compact:
        return []
    return [{"price": _from_minor_units(compact[i]), "quantity": compact[i + 1]} for i in range(0, len(compact) - 1, 2)]


def requires_login(func):
    @wraps(func)
    async def wrapper(self, *args, **kwargs):
        await self._ensure_login()
        return await func(self, *args, **kwargs)

    return wrapper


def throttled(func):
    """Pace outbound Steam calls so a batch cannot burst past Steam's limits."""

    @wraps(func)
    async def wrapper(self, *args, **kwargs):
        await self._limiter.acquire()
        return await func(self, *args, **kwargs)

    return wrapper


class SteamService:
    def __init__(self, settings: Settings):
        # The credentials go in here rather than only into login(): is_session_alive()
        # compares the account name against the page, so a client that adopted someone
        # else's session still needs to know it.
        self.client = SteamClient(
            api_key=settings.STEAM_API_KEY,
            username=settings.STEAM_USERNAME,
            password=settings.STEAM_PASSWORD,
        )
        self._username: str = settings.STEAM_USERNAME
        self._password: str = settings.STEAM_PASSWORD
        self._steam_id: str = settings.STEAMID
        self._guard: str = json.dumps(
            {
                "steamid": settings.STEAMID,
                "shared_secret": settings.STEAM_SHARED_SECRET,
                "identity_secret": settings.STEAM_IDENTITY_SECRET,
            }
        )
        self._last_check: Optional[datetime] = None
        self._redis = Redis(host=settings.REDIS_HOST, port=int(settings.REDIS_PORT))
        self._limiter = RedisRateLimiter(
            self._redis, RATE_LIMIT_KEY, STEAM_MAX_CALLS_PER_PERIOD, STEAM_RATE_LIMIT_PERIOD
        )
        self._check_interval = datetime.timedelta(minutes=5)

    def _should_check_login(self) -> bool:
        return not self._last_check or datetime.datetime.now(datetime.UTC) - self._last_check > self._check_interval

    async def _cooldown_remaining(self) -> Optional[datetime.timedelta]:
        milliseconds = await self._redis.pttl(LOGIN_BLOCK_KEY)
        if milliseconds is None or milliseconds < 0:
            return None
        return datetime.timedelta(milliseconds=milliseconds)

    async def _start_login_cooldown(self) -> datetime.timedelta:
        failures = await self._redis.incr(LOGIN_FAILURES_KEY)
        await self._redis.expire(LOGIN_FAILURES_KEY, int(LOGIN_COOLDOWN_MAX.total_seconds()) * 2)

        cooldown = min(LOGIN_COOLDOWN_BASE * 2 ** (failures - 1), LOGIN_COOLDOWN_MAX)
        await self._redis.set(LOGIN_BLOCK_KEY, failures, px=int(cooldown.total_seconds() * 1000))
        return cooldown

    async def _clear_login_cooldown(self) -> None:
        await self._redis.delete(LOGIN_BLOCK_KEY, LOGIN_FAILURES_KEY)

    @asynccontextmanager
    async def _login_lock(self):
        """
        Only one process may be logging in at a time.

        Steam refuses a second session opened moments after the first, so two processes
        starting together used to collide. Whoever loses the race waits and then finds
        the session the winner published.
        """
        token = uuid.uuid4().hex
        deadline = time.monotonic() + LOGIN_LOCK_WAIT

        while not await self._redis.set(LOGIN_LOCK_KEY, token, nx=True, ex=LOGIN_LOCK_TTL):
            if time.monotonic() > deadline:
                raise SteamLoginUnavailable("Another process has been logging in to Steam for too long.")
            await asyncio.sleep(1)

        try:
            yield
        finally:
            if await self._redis.get(LOGIN_LOCK_KEY) == token.encode():
                await self._redis.delete(LOGIN_LOCK_KEY)

    async def _save_shared_session(self) -> None:
        cookies = [
            {"name": c.name, "value": c.value, "domain": c.domain, "path": c.path} for c in self.client._session.cookies
        ]
        await self._redis.set(
            SESSION_KEY,
            json.dumps({"cookies": cookies, "steam_guard": self.client.steam_guard}),
            ex=SESSION_TTL,
        )

    async def _restore_shared_session(self) -> bool:
        """
        Adopt the session another process published, if it is still usable.

        steampy's own set_login_cookies() cannot be used: it stores the cookies without a
        domain and then reads the session id back with a domain filter, so the market
        ends up wired with a null session id. Restoring each cookie with its domain keeps
        that lookup working.

        Liveness is checked with get_steam_id() rather than is_session_alive(), which
        looks for the account name in a page that shows the persona name instead and so
        calls a healthy session dead. Matching the id also proves the cookies belong to
        the account we mean to trade with.
        """
        raw = await self._redis.get(SESSION_KEY)
        if not raw:
            return False

        try:
            stored = json.loads(raw)
            for cookie in stored["cookies"]:
                self.client._session.cookies.set(
                    cookie["name"], cookie["value"], domain=cookie["domain"], path=cookie["path"]
                )

            self.client.steam_guard = stored["steam_guard"]
            self.client.was_login_executed = True
            self.client.market._set_login_executed(self.client.steam_guard, self.client._get_session_id())

            await self._limiter.acquire()
            steam_id = str(await to_thread.run_sync(self.client.get_steam_id))

            if steam_id == self._steam_id:
                logger.info("Reusing the Steam session published by another process.")
                return True

            logger.warning(f"The stored Steam session belongs to {steam_id}, not {self._steam_id}.")
        except Exception as e:
            logger.info(f"Could not adopt the stored Steam session: {e!r}")

        # Leave the stored session alone: failing to adopt it says nothing about whether
        # it still works for the process that created it. Drop the cookies we injected
        # though, because logging in over a stale steamLoginSecure confuses Steam.
        self.client._session.cookies.clear()
        self.client.was_login_executed = False
        return False

    async def _log_in(self) -> None:
        """
        One attempt, no retry.

        Steam limits how often an account may log in, and a refusal comes back as a
        response missing the fields steampy expects. Retrying that three times within
        nine seconds spends the budget faster and digs the hole deeper; the growing
        cooldown is the right answer instead.
        """
        logger.info("Logging into Steam.")
        await self._limiter.acquire()
        await to_thread.run_sync(
            self.client.login,
            self._username,
            self._password,
            self._guard,
        )
        assert self.client.was_login_executed
        logger.info("Steam login successful.")

    async def _ensure_login(self) -> None:
        """
        Make sure a usable Steam session is in place.

        One session is shared through Redis by every process: Steam refuses a second
        session opened right after the first, so each process minting its own is what
        made logins fail. A refused login puts further attempts on a growing cooldown,
        also shared, but a process whose session is already fresh is never held back
        by it.
        """
        if not self._should_check_login():
            return

        if await self._restore_shared_session():
            self._last_check = datetime.datetime.now(datetime.UTC)
            return

        remaining = await self._cooldown_remaining()
        if remaining is not None:
            raise SteamLoginUnavailable(f"Steam login is on cooldown for another {remaining}.")

        async with self._login_lock():
            # the process that held the lock may have just published a session
            if await self._restore_shared_session():
                self._last_check = datetime.datetime.now(datetime.UTC)
                return

            try:
                await self._log_in()
            except Exception as e:
                cooldown = await self._start_login_cooldown()
                logger.error(f"Steam login failed, backing off for {cooldown}: {e!r}")
                raise SteamLoginUnavailable(f"Could not log in to Steam: {e!r}") from e

            await self._save_shared_session()
            await self._clear_login_cooldown()
            self._last_check = datetime.datetime.now(datetime.UTC)

    @requires_login
    @throttled
    async def get_inventory(self, game: GameOptions) -> dict:
        logger.debug(f"Fetching inventory for app_id = {game.app_id}.")
        return await to_thread.run_sync(self.client.get_my_inventory, game, True, 1000)

    @requires_login
    @throttled
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
    @throttled
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
            "sell_levels": _to_levels(data.get("rgCompactSellOrders")),
            "buy_levels": _to_levels(data.get("rgCompactBuyOrders")),
        }

    @requires_login
    @throttled
    async def search_market(
        self,
        app_id: str,
        start: int = 0,
        count: int = 100,
        sort_column: str = "quantity",
        sort_dir: str = "desc",
    ) -> dict:
        """
        One page of the market search, as JSON.

        `sell_listings` counts how many copies are on sale, which is a rough liquidity
        proxy; the real traded volume only comes from the price history.
        """
        logger.debug(f"Searching the market for app {app_id}, offset {start}.")
        params = {
            "query": "",
            "start": start,
            "count": count,
            "search_descriptions": 0,
            "sort_column": sort_column,
            "sort_dir": sort_dir,
            "appid": app_id,
            "norender": 1,
        }
        resp = await to_thread.run_sync(
            partial(self.client._session.get, f"{STEAM_COMMUNITY_URL}/market/search/render/", params=params, timeout=30)
        )
        resp.raise_for_status()
        return resp.json()

    @requires_login
    @throttled
    async def get_my_market_listings(self) -> dict:
        logger.debug("Fetching market listings.")
        return await to_thread.run_sync(self.client.market.get_my_market_listings)

    @requires_login
    @throttled
    async def get_wallet_balance(self) -> Decimal:
        balance = await to_thread.run_sync(self.client.get_wallet_balance, True, False)
        logger.debug(f"Wallet balance: {balance}.")
        return Decimal(balance)

    @requires_login
    @throttled
    async def cancel_buy_order(self, buy_order_id: str) -> None:
        logger.info(f"Cancelling buy order {buy_order_id}.")
        await to_thread.run_sync(self.client.market.cancel_buy_order, buy_order_id)

    @requires_login
    @throttled
    async def cancel_sell_listing(self, listing_id: str) -> None:
        logger.info(f"Cancelling sell listing {listing_id}.")
        await to_thread.run_sync(self.client.market.cancel_sell_order, listing_id)

    @requires_login
    @throttled
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
    @throttled
    async def create_sell_order(self, asset_id: str, game: GameOptions, price: Decimal) -> None:
        logger.debug(f"Creating a sell order for {asset_id} at {price} rub.")
        kopecks = int((price * 100).to_integral_value())
        net_received = str(calculate_fees(gross=kopecks)["net_received"])
        resp = await to_thread.run_sync(self.client.market.create_sell_order, asset_id, game, net_received)
        if not resp.get("success", False):
            logger.error(f"Failed to create a sell order for {asset_id} at {price} rub. Response: {resp}")
            raise SellOrderFailed(f"Steam rejected the sell order for {asset_id}: {resp}")
        logger.info(f"Sell order for {asset_id} accepted by Steam. Response: {resp}")
