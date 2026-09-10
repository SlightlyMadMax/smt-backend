import asyncio
import json
import statistics
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

from redis.asyncio import Redis
from steampy.models import GameOptions

from smt.logger import get_logger
from smt.services.market_analytics import MarketAnalyticsService
from smt.services.steam import SteamService
from smt.utils.math import weighted_percentile
from smt.utils.steam import net_received


logger = get_logger("services.market_scan")

PAGE_SIZE = 100
ICON_BASE = "https://steamcommunity-a.akamaihd.net/economy/image/"
SCAN_KEY = "smt:scan:"
LATEST_KEY = "smt:scan:latest"
SCAN_TTL = 7 * 24 * 3600


@dataclass
class ScanParams:
    app_id: str = "440"
    context_id: str = "2"
    limit: int = 50
    days: int = 30
    buy_percentile: int = 10
    sell_percentile: int = 90
    min_price: Decimal = Decimal("1.00")
    max_price: Decimal = Decimal("100.00")
    min_volume: int = 100
    max_drift: Decimal = Decimal("2")

    @classmethod
    def from_dict(cls, raw: dict) -> "ScanParams":
        defaults = cls()
        return cls(
            app_id=str(raw.get("app_id") or defaults.app_id),
            context_id=str(raw.get("context_id") or defaults.context_id),
            limit=int(raw.get("limit") or defaults.limit),
            days=int(raw.get("days") or defaults.days),
            buy_percentile=int(raw.get("buy_percentile") or defaults.buy_percentile),
            sell_percentile=int(raw.get("sell_percentile") or defaults.sell_percentile),
            min_price=Decimal(str(raw.get("min_price", defaults.min_price))),
            max_price=Decimal(str(raw.get("max_price", defaults.max_price))),
            min_volume=int(raw.get("min_volume", defaults.min_volume)),
            max_drift=Decimal(str(raw.get("max_drift", defaults.max_drift))),
        )

    def as_dict(self) -> dict:
        return {k: str(v) if isinstance(v, Decimal) else v for k, v in asdict(self).items()}


@dataclass
class Candidate:
    market_hash_name: str
    name: str
    icon_url: str
    app_id: str
    context_id: str
    listings: int
    current_price: Decimal
    volume_30d: int = 0
    buy_target: Optional[Decimal] = None
    sell_target: Optional[Decimal] = None
    spread_pct: Optional[Decimal] = None
    required_pct: Optional[Decimal] = None
    profit_per_trade: Optional[Decimal] = None
    round_trips: int = 0
    queue_ahead: Optional[int] = None
    days_to_clear: Optional[Decimal] = None
    feasible_round_trips: int = 0
    median_hold_hours: Optional[Decimal] = None
    profit_per_window: Optional[Decimal] = None
    return_on_capital_pct: Optional[Decimal] = None
    median_price: Optional[Decimal] = None
    price_drift: Optional[Decimal] = None
    tradable: bool = False
    note: str = ""

    def as_dict(self) -> dict:
        return {k: str(v) if isinstance(v, Decimal) else v for k, v in asdict(self).items()}


@dataclass
class ScanState:
    id: str
    params: ScanParams
    status: str = "running"
    collected: int = 0
    measured: int = 0
    error: str = ""
    started_at: str = ""
    finished_at: str = ""
    candidates: List[Candidate] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "collected": self.collected,
            "measured": self.measured,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "params": self.params.as_dict(),
            "candidates": [c.as_dict() for c in self.candidates],
        }


def required_spread_pct(buy: Decimal) -> Decimal:
    """How far above `buy` the sell price must sit for the round trip to break even."""
    sell = buy
    step = Decimal("0.01")
    while net_received(sell) < buy:
        sell += step
    return ((sell / buy - 1) * 100).quantize(Decimal("0.01"))


@dataclass
class Point:
    """Steam hands history back as tuples; the analytics service reads stored records."""

    recorded_at: datetime
    price: Decimal
    volume: int


def to_points(history: List[tuple]) -> List[Point]:
    return [Point(recorded_at=moment, price=price, volume=volume) for moment, price, volume in history]


def candidate_from_search_row(row: dict, app_id: str, context_id: str) -> Candidate:
    description = row.get("asset_description") or {}
    icon = description.get("icon_url") or ""
    return Candidate(
        market_hash_name=row["hash_name"],
        name=row.get("name") or row["hash_name"],
        icon_url=f"{ICON_BASE}{icon}" if icon else "",
        app_id=str(description.get("appid") or app_id),
        context_id=context_id,
        listings=int(row.get("sell_listings") or 0),
        current_price=Decimal(row.get("sell_price", 0)) / 100,
    )


class MarketScanService:
    """
    Rank market items by how well they suit the strategy, before we own any of them.

    A scan costs one Steam request per item and takes minutes, so it runs as a background
    job and reports progress through Redis. Results are disposable: you re-run a scan
    rather than consult an old one, so they expire instead of living in the database.
    """

    def __init__(self, steam_service: SteamService, redis: Redis):
        self.steam = steam_service
        self.redis = redis

    @staticmethod
    def new_id() -> str:
        return uuid.uuid4().hex

    async def get(self, scan_id: str) -> Optional[dict]:
        raw = await self.redis.get(f"{SCAN_KEY}{scan_id}")
        return json.loads(raw) if raw else None

    async def latest(self) -> Optional[dict]:
        scan_id = await self.redis.get(LATEST_KEY)
        if not scan_id:
            return None
        return await self.get(scan_id.decode() if isinstance(scan_id, bytes) else scan_id)

    async def _save(self, state: ScanState) -> None:
        await self.redis.set(f"{SCAN_KEY}{state.id}", json.dumps(state.as_dict()), ex=SCAN_TTL)
        await self.redis.set(LATEST_KEY, state.id, ex=SCAN_TTL)

    async def run(self, scan_id: str, params: ScanParams) -> None:
        state = ScanState(id=scan_id, params=params, started_at=datetime.now(timezone.utc).isoformat())
        await self._save(state)

        try:
            candidates = await self._collect(state)
            await self._measure(state, candidates)
            state.status = "done"
        except asyncio.CancelledError:
            state.status = "failed"
            state.error = (
                f"Stopped after measuring {state.measured} of {state.params.limit} items. "
                f"The results so far are kept."
            )
            await self._finish(state)
            raise
        except Exception as e:
            logger.exception("Market scan failed")
            state.status = "failed"
            state.error = f"{type(e).__name__}: {e}"

        await self._finish(state)

    async def _finish(self, state: ScanState) -> None:
        state.finished_at = datetime.now(timezone.utc).isoformat()
        await self._save(state)

    async def _collect(self, state: ScanState) -> List[Candidate]:
        params = state.params
        collected: List[Candidate] = []
        start = 0

        while len(collected) < params.limit:
            page = await self.steam.search_market(app_id=params.app_id, start=start, count=PAGE_SIZE)
            results = page.get("results") or []
            if not results:
                break

            for row in results:
                price = Decimal(row.get("sell_price", 0)) / 100
                if not (params.min_price <= price <= params.max_price):
                    continue
                collected.append(candidate_from_search_row(row, params.app_id, params.context_id))
                if len(collected) >= params.limit:
                    break

            state.collected = len(collected)
            await self._save(state)

            start += PAGE_SIZE
            if start >= int(page.get("total_count") or 0):
                break

        return collected

    async def _measure(self, state: ScanState, candidates: List[Candidate]) -> None:
        for candidate in candidates:
            try:
                await self.measure(candidate, state.params)
            except Exception as e:
                candidate.note = f"{type(e).__name__}: {e}"
                logger.warning(f"Could not measure {candidate.market_hash_name}: {e!r}")

            state.measured += 1
            state.candidates.append(candidate)
            await self._save(state)

    async def measure(self, candidate: Candidate, params: ScanParams) -> Candidate:
        history = await self.steam.get_price_history(
            market_hash_name=candidate.market_hash_name,
            game=GameOptions(params.app_id, params.context_id),
            days=params.days,
        )
        points = MarketAnalyticsService.filter_price_outliers(to_points(history))
        if len(points) < 2:
            candidate.note = "not enough history"
            return candidate

        candidate.volume_30d = sum(point.volume for point in points)
        candidate.median_price = statistics.median(point.price for point in points)

        if candidate.current_price > 0:
            candidate.price_drift = (candidate.median_price / candidate.current_price).quantize(Decimal("0.01"))
            if not MarketAnalyticsService.history_describes_current_market(
                points, candidate.current_price, params.max_drift
            ):
                candidate.note = f"history is {candidate.price_drift}x the current price"
                return candidate

        if candidate.volume_30d < params.min_volume:
            candidate.note = f"only {candidate.volume_30d} sold over the window"
            return candidate

        prices = [point.price for point in points]
        volumes = [point.volume for point in points]
        candidate.buy_target = weighted_percentile(prices, volumes, params.buy_percentile)
        candidate.sell_target = weighted_percentile(prices, volumes, params.sell_percentile)

        if candidate.buy_target <= 0:
            candidate.note = "no usable buy target"
            return candidate

        candidate.spread_pct = ((candidate.sell_target / candidate.buy_target - 1) * 100).quantize(Decimal("0.01"))
        candidate.required_pct = required_spread_pct(candidate.buy_target)
        candidate.profit_per_trade = (net_received(candidate.sell_target) - candidate.buy_target).quantize(
            Decimal("0.01")
        )
        candidate.tradable = candidate.profit_per_trade > 0

        candidate.round_trips, candidate.median_hold_hours = MarketAnalyticsService.simulate_round_trips(
            points, candidate.buy_target, candidate.sell_target
        )

        await self._measure_the_queue(candidate, params)

        candidate.profit_per_window = (candidate.profit_per_trade * candidate.feasible_round_trips).quantize(
            Decimal("0.01")
        )
        candidate.return_on_capital_pct = (candidate.profit_per_window / candidate.buy_target * 100).quantize(
            Decimal("0.1")
        )
        return candidate

    async def _measure_the_queue(self, candidate: Candidate, params: ScanParams) -> None:
        """
        Ask the order book how many sellers stand in front of us at our own price.

        Without this the history alone decides, and the history has no idea whether the
        buyer who pushed the price up would have bought from us or from the 800 cheaper
        listings underneath.
        """
        candidate.feasible_round_trips = candidate.round_trips

        try:
            book = await self.steam.get_order_book(market_hash_name=candidate.market_hash_name, app_id=candidate.app_id)
        except Exception as e:
            logger.warning(f"No order book for {candidate.market_hash_name}, the queue is unknown: {e!r}")
            return

        candidate.queue_ahead = MarketAnalyticsService.queue_ahead(book.get("sell_levels") or [], candidate.sell_target)
        candidate.days_to_clear = MarketAnalyticsService.days_to_clear(
            candidate.queue_ahead, Decimal(candidate.volume_30d) / params.days
        )
        candidate.feasible_round_trips = MarketAnalyticsService.feasible_round_trips(
            candidate.round_trips, candidate.days_to_clear, params.days
        )
