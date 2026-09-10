import asyncio
import datetime
import json
import re
import time
import uuid
from contextlib import asynccontextmanager
from decimal import Decimal
from functools import partial, wraps
from typing import Optional
from urllib.parse import quote

import httpx
from anyio import to_thread
from redis.asyncio import Redis
from steampy import guard
from steampy.client import SteamClient
from steampy.exceptions import TooManyRequests
from steampy.models import Currency, GameOptions

from smt.core.config import Settings
from smt.exceptions import (
    BuyOrderFailed,
    BuyOrderStatusUnavailable,
    ConfirmationFailed,
    OrderBookUnavailable,
    SellOrderFailed,
    SteamLoginUnavailable,
    SteamThrottled,
)
from smt.logger import get_logger
from smt.utils.rate_limit import RedisRateLimiter
from smt.utils.steam import FeeSchedule, calculate_fees, parse_steam_ts, set_fee_schedule


logger = get_logger("services.steam")

STEAM_COMMUNITY_URL = "https://steamcommunity.com"
CONFIRMATION_URL = f"{STEAM_COMMUNITY_URL}/mobileconf"
CONFIRMATION_ATTEMPTS = 4
CONFIRMATION_DELAY = 3.0
ORDER_PENDING_CONFIRMATION = 22
LISTING_CONFIRMATION_TYPE = 3

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)
MOBILE_USER_AGENT = (
    "Mozilla/5.0 (Linux; U; Android 9; en-us; Valve Steam App Version/3) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/44.0.2403.133 Mobile Safari/537.36"
)
UNWELCOME_HEADERS = ("Accept", "Accept-Language", "Accept-Encoding", "Connection")
WEB_HEADERS = {"User-Agent": BROWSER_USER_AGENT}
MOBILE_HEADERS = {
    "User-Agent": MOBILE_USER_AGENT,
    "X-Requested-With": "com.valvesoftware.android.steam.community",
}
ORDER_BOOK_TIMEOUT = 30
ACCOUNT_CURRENCY = Currency.RUB
SOLD_EVENT_TYPE = 3
MARKET_HISTORY_PAGE = 100
RATE_LIMIT_KEY = "smt:steam:calls"
LOGIN_BLOCK_KEY = "smt:steam:login_block"
LOGIN_FAILURES_KEY = "smt:steam:login_failures"
LOGIN_LOCK_KEY = "smt:steam:login_lock"
SESSION_KEY = "smt:steam:session"
FEE_SCHEDULE_KEY = "smt:steam:fee_schedule"
LOGIN_LOCK_TTL = 60
LOGIN_LOCK_WAIT = 90
SESSION_TTL = 60 * 60 * 12
FEE_SCHEDULE_TTL = 60 * 60 * 24
WALLET_INFO_PATTERN = re.compile(r"g_rgWalletInfo\s*=\s*(\{.*?\});", re.S)
STEAM_RATE_LIMIT_PERIOD = 60.0

# Steam meters each endpoint separately, and far from evenly.
STEAM_BUDGETS = {
    "market": 10,
    "pricehistory": 18,
    "inventory": 6,
    "mobileconf": 5,
    "orderbook": 20,
    "orders": 10,
    "login": 4,
    "default": 15,
}
COOLDOWN_KEY = "smt:steam:cooldown:"
REFUSAL_COUNT_KEY = "smt:steam:refusals:"
COOLDOWN_BASE = 180
COOLDOWN_MAX = 3600
LOGIN_COOLDOWN_BASE = datetime.timedelta(minutes=5)
LOGIN_COOLDOWN_MAX = datetime.timedelta(hours=1)


def _from_minor_units(value) -> Optional[Decimal]:
    """Steam quotes order book prices in minor units, e.g. 682 for 6.82 RUB."""
    return None if value is None else (Decimal(value) / 100).quantize(Decimal("0.01"))


def _paid_from_purchases(purchases: list) -> Optional[Decimal]:
    """Total the buyer actually paid, once Steam tells us what the fills cost."""
    total = 0
    seen = False
    for purchase in purchases:
        if not isinstance(purchase, dict):
            continue
        amount = purchase.get("price_total")
        if amount is None:
            subtotal = purchase.get("price_subtotal")
            if subtotal is None:
                continue
            amount = int(subtotal) + int(purchase.get("price_fee") or 0)
        seen = True
        total += int(amount)
    return _from_minor_units(total) if seen else None


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


def _was_refused_for_frequency(error: Exception) -> bool:
    if isinstance(error, TooManyRequests):
        return True
    status = getattr(getattr(error, "response", None), "status_code", None)
    return status == 429 or "429" in str(error)


def throttled(bucket: str = "default"):
    """Pace outbound Steam calls, and stand back when Steam says no."""

    def decorate(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            await self._take_a_slot(bucket)
            try:
                result = await func(self, *args, **kwargs)
            except Exception as e:
                if _was_refused_for_frequency(e):
                    await self._stand_back(bucket)
                raise

            await self._worked_again(bucket)
            return result

        return wrapper

    return decorate


class SteamService:
    def __init__(self, settings: Settings):
        self.client = SteamClient(
            api_key=settings.STEAM_API_KEY,
            username=settings.STEAM_USERNAME,
            password=settings.STEAM_PASSWORD,
        )
        for header in UNWELCOME_HEADERS:
            self.client._session.headers.pop(header, None)
        self.client._session.headers.update(WEB_HEADERS)
        self._username: str = settings.STEAM_USERNAME
        self._password: str = settings.STEAM_PASSWORD
        self._steam_id: str = settings.STEAMID
        self._identity_secret: str = settings.STEAM_IDENTITY_SECRET
        self._guard: str = json.dumps(
            {
                "steamid": settings.STEAMID,
                "shared_secret": settings.STEAM_SHARED_SECRET,
                "identity_secret": settings.STEAM_IDENTITY_SECRET,
            }
        )
        self._last_check: Optional[datetime] = None
        self._redis = Redis(
            host=settings.REDIS_HOST,
            port=int(settings.REDIS_PORT),
            password=settings.REDIS_PASSWORD,
        )
        self._limiters = {
            bucket: RedisRateLimiter(self._redis, f"{RATE_LIMIT_KEY}:{bucket}", calls, STEAM_RATE_LIMIT_PERIOD)
            for bucket, calls in STEAM_BUDGETS.items()
        }
        self._check_interval = datetime.timedelta(minutes=5)

    def _confirmation_params(self, tag: str) -> dict:
        timestamp = int(time.time())
        return {
            "p": guard.generate_device_id(self._steam_id),
            "a": self._steam_id,
            "k": guard.generate_confirmation_key(self._identity_secret, tag, timestamp),
            "t": timestamp,
            "m": "android",
            "tag": tag,
        }

    async def _pending_confirmations(self) -> list:
        await self._take_a_slot("mobileconf")
        resp = await to_thread.run_sync(
            partial(
                self.client._session.get,
                f"{CONFIRMATION_URL}/getlist",
                params=self._confirmation_params("conf"),
                headers=MOBILE_HEADERS,
                timeout=ORDER_BOOK_TIMEOUT,
            )
        )
        resp.raise_for_status()
        payload = resp.json()
        if not payload.get("success"):
            raise ConfirmationFailed(f"Steam would not list confirmations: {payload}")
        return payload.get("conf") or []

    async def _answer_confirmation(self, confirmation: dict, op: str) -> None:
        params = self._confirmation_params(op)
        params.update({"op": op, "cid": confirmation["id"], "ck": confirmation["nonce"]})

        await self._take_a_slot("mobileconf")
        resp = await to_thread.run_sync(
            partial(
                self.client._session.get,
                f"{CONFIRMATION_URL}/ajaxop",
                params=params,
                headers={**MOBILE_HEADERS, "X-Requested-With": "XMLHttpRequest"},
                timeout=ORDER_BOOK_TIMEOUT,
            )
        )
        resp.raise_for_status()
        if not resp.json().get("success"):
            raise ConfirmationFailed(f"Steam rejected the answer to confirmation {confirmation['id']}: {resp.text}")

    async def _find_confirmation(self, matches) -> Optional[dict]:
        """The list can lag behind the request and can fail transiently, so keep looking."""
        for attempt in range(CONFIRMATION_ATTEMPTS):
            try:
                found = [c for c in await self._pending_confirmations() if matches(c)]
            except Exception as e:
                logger.warning(f"Could not read the confirmation list: {e!r}")
                found = []

            if len(found) > 1:
                raise ConfirmationFailed(f"{len(found)} confirmations match, refusing to guess which one is ours.")
            if found:
                return found[0]
            if attempt < CONFIRMATION_ATTEMPTS - 1:
                await asyncio.sleep(CONFIRMATION_DELAY)
        return None

    async def _confirm(self, matches, what: str) -> None:
        confirmation = await self._find_confirmation(matches)
        if not confirmation:
            raise ConfirmationFailed(f"Steam asked to confirm {what} but no matching confirmation appeared.")

        logger.info(f"Confirming {what} through confirmation {confirmation['id']}.")
        await self._answer_confirmation(confirmation, "allow")

    async def _take_a_slot(self, bucket: str) -> None:
        remaining = await self._redis.pttl(f"{COOLDOWN_KEY}{bucket}")
        if remaining and remaining > 0:
            raise SteamThrottled(
                f"Steam refused {bucket} requests for being too frequent; "
                f"waiting another {remaining // 1000}s before trying again."
            )
        await self._limiters.get(bucket, self._limiters["default"]).acquire()

    async def _stand_back(self, bucket: str) -> None:
        """
        Each refusal waits longer than the last.

        Steam keeps its own timer, and probing while it is still counting appears to extend
        it, so a fixed pause can hold us in the penalty box indefinitely.
        """
        refusals = await self._redis.incr(f"{REFUSAL_COUNT_KEY}{bucket}")
        await self._redis.expire(f"{REFUSAL_COUNT_KEY}{bucket}", COOLDOWN_MAX * 2)

        wait = min(COOLDOWN_BASE * 2 ** (refusals - 1), COOLDOWN_MAX)
        await self._redis.set(f"{COOLDOWN_KEY}{bucket}", 1, ex=wait)
        logger.warning(
            f"Steam refused a {bucket} request for being too frequent "
            f"({refusals} in a row), leaving it alone for {wait}s."
        )

    async def _worked_again(self, bucket: str) -> None:
        await self._redis.delete(f"{REFUSAL_COUNT_KEY}{bucket}")

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
        """Only one process may be logging in at a time."""
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
        """Adopt the session another process published, if it is still usable."""
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

            await self._take_a_slot("login")
            steam_id = str(await to_thread.run_sync(self.client.get_steam_id))

            if steam_id == self._steam_id:
                logger.info("Reusing the Steam session published by another process.")
                return True

            logger.warning(f"The stored Steam session belongs to {steam_id}, not {self._steam_id}.")
        except Exception as e:
            logger.info(f"Could not adopt the stored Steam session: {e!r}")

        self.client._session.cookies.clear()
        self.client.was_login_executed = False
        return False

    async def _log_in(self) -> None:
        """One attempt, no retry."""
        logger.info("Logging into Steam.")
        await self._take_a_slot("login")
        await to_thread.run_sync(
            self.client.login,
            self._username,
            self._password,
            self._guard,
        )
        assert self.client.was_login_executed
        logger.info("Steam login successful.")

    def _schedule_from(self, info: dict) -> FeeSchedule:
        return FeeSchedule(
            steam_percent=Decimal(str(info["wallet_fee_percent"])),
            publisher_percent=Decimal(str(info["wallet_publisher_fee_percent_default"])),
            minimum=int(info["wallet_fee_minimum"]),
            base=int(info["wallet_fee_base"]),
        )

    async def _load_fee_schedule(self) -> None:
        """Steam publishes its fee parameters on the market page; they are not constants."""
        cached = await self._redis.get(FEE_SCHEDULE_KEY)
        if cached:
            set_fee_schedule(self._schedule_from(json.loads(cached)))
            return

        try:
            await self._take_a_slot("market")
            resp = await to_thread.run_sync(
                partial(self.client._session.get, f"{STEAM_COMMUNITY_URL}/market/", timeout=ORDER_BOOK_TIMEOUT)
            )
            match = WALLET_INFO_PATTERN.search(resp.text)
            if not match:
                logger.warning("Steam did not include g_rgWalletInfo, keeping the current fee schedule.")
                return

            info = json.loads(match.group(1))
            wanted = {
                key: info[key]
                for key in (
                    "wallet_fee_percent",
                    "wallet_publisher_fee_percent_default",
                    "wallet_fee_minimum",
                    "wallet_fee_base",
                )
            }
            set_fee_schedule(self._schedule_from(wanted))
            await self._redis.set(FEE_SCHEDULE_KEY, json.dumps(wanted), ex=FEE_SCHEDULE_TTL)
        except Exception as e:
            logger.warning(f"Could not read the Steam fee schedule: {e!r}")

    async def _ensure_login(self) -> None:
        await self._establish_session()
        await self._load_fee_schedule()

    async def _establish_session(self) -> None:
        """Make sure a usable Steam session is in place."""
        if not self._should_check_login():
            return

        if await self._restore_shared_session():
            self._last_check = datetime.datetime.now(datetime.UTC)
            return

        remaining = await self._cooldown_remaining()
        if remaining is not None:
            raise SteamLoginUnavailable(f"Steam login is on cooldown for another {remaining}.")

        async with self._login_lock():
            if await self._restore_shared_session():
                self._last_check = datetime.datetime.now(datetime.UTC)
                return

            try:
                await self._log_in()
            except SteamThrottled:
                raise
            except Exception as e:
                cooldown = await self._start_login_cooldown()
                logger.error(f"Steam login failed, backing off for {cooldown}: {e!r}")
                raise SteamLoginUnavailable(f"Could not log in to Steam: {e!r}") from e

            await self._save_shared_session()
            await self._clear_login_cooldown()
            self._last_check = datetime.datetime.now(datetime.UTC)

    @requires_login
    @throttled("inventory")
    async def get_inventory(self, game: GameOptions) -> dict:
        logger.debug(f"Fetching inventory for app_id = {game.app_id}.")
        return await to_thread.run_sync(self.client.get_my_inventory, game, True, 1000)

    @requires_login
    @throttled("pricehistory")
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
    @throttled("orderbook")
    async def get_order_book(self, market_hash_name: str, app_id: str) -> dict:
        """Fetch the current order book for an item."""
        logger.debug(f"Fetching order book for {market_hash_name}.")
        params = {"q": "Load", "qp": json.dumps([int(app_id), market_hash_name], separators=(",", ":"))}
        cookies = self.client._session.cookies.get_dict(domain="steamcommunity.com")

        try:
            async with httpx.AsyncClient(timeout=ORDER_BOOK_TIMEOUT, headers=WEB_HEADERS) as client:
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
    @throttled("default")
    async def search_market(
        self,
        app_id: str,
        start: int = 0,
        count: int = 100,
        sort_column: str = "quantity",
        sort_dir: str = "desc",
    ) -> dict:
        """One page of the market search, as JSON."""
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
    @throttled("orders")
    async def get_buy_order_status(self, buy_order_id: str, market_hash_name: str, app_id: str) -> dict:
        """What Steam says became of a buy order. The endpoint answers 400 without a Referer."""
        listing_url = f"{STEAM_COMMUNITY_URL}/market/listings/{app_id}/{quote(market_hash_name)}"
        resp = await to_thread.run_sync(
            partial(
                self.client._session.get,
                f"{STEAM_COMMUNITY_URL}/market/getbuyorderstatus/",
                params={"sessionid": self.client._get_session_id(), "buy_orderid": buy_order_id},
                headers={"Referer": listing_url},
                timeout=ORDER_BOOK_TIMEOUT,
            )
        )
        resp.raise_for_status()
        data = resp.json()

        if not data.get("success"):
            raise BuyOrderStatusUnavailable(f"Steam returned no status for buy order {buy_order_id}: {data}")

        purchases = data.get("purchases") or []
        if purchases:
            logger.info(f"Buy order {buy_order_id} reports purchases: {json.dumps(purchases, ensure_ascii=False)}")

        return {
            "active": bool(data.get("active")),
            "purchased": int(data.get("purchased") or 0),
            "quantity": int(data.get("quantity") or 0),
            "quantity_remaining": int(data.get("quantity_remaining") or 0),
            "paid": _paid_from_purchases(purchases),
            "purchases": purchases,
        }

    @requires_login
    @throttled("market")
    async def get_sold_listings(self, count: int = MARKET_HISTORY_PAGE) -> dict:
        """Listings Steam's own history reports as sold, keyed by listing id."""
        logger.debug("Fetching market history.")
        resp = await to_thread.run_sync(
            partial(
                self.client._session.get,
                f"{STEAM_COMMUNITY_URL}/market/myhistory",
                params={"norender": 1, "start": 0, "count": count},
                timeout=ORDER_BOOK_TIMEOUT,
            )
        )
        resp.raise_for_status()
        data = resp.json()

        purchases = data.get("purchases") or {}
        sold = {}
        oldest = None

        for event in data.get("events") or []:
            occurred = datetime.datetime.fromtimestamp(event["time_event"], datetime.UTC)
            oldest = occurred if oldest is None else min(oldest, occurred)

            if event.get("event_type") != SOLD_EVENT_TYPE:
                continue

            purchase = purchases.get(f"{event['listingid']}_{event.get('purchaseid')}") or {}
            if purchase.get("failed") or purchase.get("needs_rollback"):
                continue

            received = purchase.get("received_amount")
            sold[str(event["listingid"])] = {
                "sold_at": occurred,
                "net_proceeds": _from_minor_units(received),
                "asset_id": (purchase.get("asset") or {}).get("id"),
            }

        return {"sold": sold, "oldest_event_at": oldest}

    @requires_login
    @throttled("market")
    async def get_my_market_listings(self) -> dict:
        logger.debug("Fetching market listings.")
        return await to_thread.run_sync(self.client.market.get_my_market_listings)

    @requires_login
    @throttled("market")
    async def get_wallet_balance(self) -> Decimal:
        balance = await to_thread.run_sync(self.client.get_wallet_balance, True, False)
        logger.debug(f"Wallet balance: {balance}.")
        return Decimal(balance)

    @requires_login
    @throttled("orders")
    async def cancel_buy_order(self, buy_order_id: str) -> None:
        logger.info(f"Cancelling buy order {buy_order_id}.")
        await to_thread.run_sync(self.client.market.cancel_buy_order, buy_order_id)

    @requires_login
    @throttled("orders")
    async def cancel_sell_listing(self, listing_id: str) -> None:
        logger.info(f"Cancelling sell listing {listing_id}.")
        await to_thread.run_sync(self.client.market.cancel_sell_order, listing_id)

    async def _post_buy_order(self, data: dict, listing_url: str) -> dict:
        resp = await to_thread.run_sync(
            partial(
                self.client._session.post,
                f"{STEAM_COMMUNITY_URL}/market/createbuyorder/",
                data=data,
                headers={"Referer": listing_url},
                timeout=ORDER_BOOK_TIMEOUT,
            )
        )
        return resp.json()

    @requires_login
    @throttled("orders")
    async def create_buy_order(self, market_hash_name: str, price: Decimal, game: GameOptions, quantity: int) -> str:
        """
        Steam may hold the order for a mobile confirmation.

        The confirmed order only comes into existence when the same request is sent again
        carrying the confirmation id, so the first response never has the order id.
        """
        logger.debug(f"Creating a buy order for {quantity} {market_hash_name}.")
        kopecks = int((price * 100).to_integral_value())
        listing_url = f"{STEAM_COMMUNITY_URL}/market/listings/{game.app_id}/{quote(market_hash_name)}"
        data = {
            "sessionid": self.client._get_session_id(),
            "currency": ACCOUNT_CURRENCY.value,
            "appid": game.app_id,
            "market_hash_name": market_hash_name,
            "price_total": str(kopecks * quantity),
            "tradefee_tax": 0,
            "quantity": quantity,
            "billing_state": "",
            "save_my_address": 0,
            "confirmation": 0,
        }

        payload = await self._post_buy_order(data, listing_url)

        if payload.get("need_confirmation"):
            confirmation_id = str((payload.get("confirmation") or {}).get("confirmation_id") or "")
            await self._confirm(
                lambda c: str(c.get("creator_id")) == confirmation_id,
                f"a buy order for {market_hash_name}",
            )
            data["confirmation"] = confirmation_id
            payload = await self._post_buy_order(data, listing_url)

        if payload.get("success") != 1:
            logger.error(f"Failed to create a buy order for {quantity} {market_hash_name}. Response: {payload}")
            raise BuyOrderFailed(f"Steam rejected the buy order for {market_hash_name}: {payload}")

        buy_order_id = str(payload["buy_orderid"])
        logger.info(f"Buy order with id {buy_order_id} successfully created.")
        return buy_order_id

    @requires_login
    @throttled("orders")
    async def create_sell_order(self, asset_id: str, game: GameOptions, price: Decimal) -> None:
        logger.debug(f"Creating a sell order for {asset_id} at {price} rub.")
        kopecks = int((price * 100).to_integral_value())
        net_received = calculate_fees(gross=kopecks)["net_received"]

        resp = await to_thread.run_sync(
            partial(
                self.client._session.post,
                f"{STEAM_COMMUNITY_URL}/market/sellitem/",
                data={
                    "assetid": asset_id,
                    "sessionid": self.client._get_session_id(),
                    "contextid": game.context_id,
                    "appid": game.app_id,
                    "amount": 1,
                    "price": net_received,
                },
                headers={"Referer": f"{STEAM_COMMUNITY_URL}/profiles/{self._steam_id}/inventory"},
                timeout=ORDER_BOOK_TIMEOUT,
            )
        )
        payload = resp.json()

        if payload.get("needs_mobile_confirmation"):
            await self._confirm(
                lambda c: c.get("type") == LISTING_CONFIRMATION_TYPE,
                f"the listing of asset {asset_id}",
            )
            logger.info(f"Sell order for {asset_id} confirmed.")
            return

        if not payload.get("success"):
            logger.error(f"Failed to create a sell order for {asset_id} at {price} rub. Response: {payload}")
            raise SellOrderFailed(f"Steam rejected the sell order for {asset_id}: {payload}")

        logger.info(f"Sell order for {asset_id} accepted by Steam. Response: {payload}")
