import math
import statistics
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import List, Optional, Tuple

from smt.db.models import PriceHistoryRecord
from smt.services.settings import SettingsService
from smt.utils.math import weighted_percentile
from smt.utils.steam import calculate_fees, minimum_listing_price, net_received


OUTLIER_PRICE_FACTOR = Decimal("5")


@dataclass
class ItemIndicators:
    profit: Decimal
    volume24h: Optional[int]
    volume7d: Optional[int]
    volatility: Decimal
    round_trips: int
    median_hold_hours: Optional[Decimal]
    return_on_capital_30d: Optional[Decimal]


PRICE_DRIFT_FACTOR = Decimal("2")
SELL_SEARCH_FLOOR = 50
WEEKLY_WINDOW = timedelta(days=7)
JUDGEMENT_SETTINGS = (
    "analysis_window_days",
    "buy_percentile",
    "sell_percentile",
    "min_profit_threshold",
    "min_volume_24h",
    "min_volume_7d",
    "max_volatility_threshold",
    "max_hold_hours",
    "min_return_on_capital_30d",
)


@dataclass
class SellChoice:
    """One candidate asking price, and what the history and the order book say it would do."""

    percentile: int
    price: Decimal
    profit: Decimal
    round_trips: int
    median_hold_hours: Optional[Decimal]
    queue_ahead: Optional[int]
    days_to_clear: Optional[Decimal]
    feasible_round_trips: int

    @property
    def profit_per_window(self) -> Decimal:
        return (self.profit * self.feasible_round_trips).quantize(Decimal("0.01"))


@dataclass
class Evaluation:
    """Everything the bot concludes about an item from its history and its order book."""

    tradable: bool
    reason: str
    outliers_dropped: int = 0
    buy_target: Optional[Decimal] = None
    choice: Optional[SellChoice] = None
    volatility: Optional[Decimal] = None
    volume7d: Optional[int] = None
    return_on_capital_30d: Optional[Decimal] = None


class MarketAnalyticsService:
    def __init__(self, settings_service: SettingsService):
        self.settings_service = settings_service

    @staticmethod
    def filter_price_outliers(
        records: List[PriceHistoryRecord], factor: Decimal = OUTLIER_PRICE_FACTOR
    ) -> List[PriceHistoryRecord]:
        """Drop records whose price is more than `factor` times away from the median."""
        if not records:
            return []

        median = statistics.median(r.price for r in records)
        if median <= 0:
            return list(records)

        low, high = median / factor, median * factor
        return [r for r in records if low <= r.price <= high]

    @staticmethod
    def history_describes_current_market(
        records: List[PriceHistoryRecord],
        current_price: Optional[Decimal],
        factor: Decimal = PRICE_DRIFT_FACTOR,
    ) -> bool:
        """Whether the price history says anything about what can be bought right now."""
        if not records or current_price is None or current_price <= 0:
            return True

        median = statistics.median(r.price for r in records)
        drift = median / current_price
        return 1 / factor <= drift <= factor

    async def compute_weighted_percentile_targets(self, records: List[PriceHistoryRecord]) -> Tuple[Decimal, Decimal]:
        settings = await self.settings_service.get_settings()
        buy_pct = settings.buy_percentile
        sell_pct = settings.sell_percentile

        prices = [r.price for r in records]
        vols = [r.volume for r in records]
        buy = weighted_percentile(prices, vols, buy_pct)
        sell = weighted_percentile(prices, vols, sell_pct)
        return buy, sell

    @staticmethod
    async def compute_recent_stats(
        records: List[PriceHistoryRecord], window: timedelta = timedelta(hours=24)
    ) -> Tuple[Optional[Decimal], Optional[int]]:
        """Return the volume weighted median price and the traded volume within `window`."""
        if not records:
            return None, None

        latest = max(r.recorded_at for r in records)
        recent = [r for r in records if latest - r.recorded_at < window]
        if not recent:
            return None, None

        prices = [r.price for r in recent]
        volumes = [r.volume for r in recent]
        total_volume = sum(volumes)
        if total_volume == 0:
            return None, 0

        return weighted_percentile(prices, volumes, 50), total_volume

    @staticmethod
    async def compute_volume_weighted_volatility(records: List[PriceHistoryRecord]) -> Decimal:
        prices = [float(r.price) for r in records]
        vols = [r.volume for r in records]
        returns = [math.log(prices[i] / prices[i - 1]) for i in range(1, len(prices))]
        weights = [(vols[i] + vols[i - 1]) / 2 for i in range(1, len(vols))]
        total_w = sum(weights)
        if total_w == 0:
            return Decimal("0.0000")
        mean_ret = sum(r * w for r, w in zip(returns, weights)) / total_w
        var = sum(w * (r - mean_ret) ** 2 for r, w in zip(returns, weights)) / total_w
        sigma = math.sqrt(var)
        return Decimal(sigma).quantize(Decimal("0.0001"))

    @staticmethod
    async def compute_net_and_profit(opt_sell: Decimal, opt_buy: Decimal) -> Tuple[Decimal, Decimal]:
        gross = int((opt_sell * 100).to_integral_value())
        fees = calculate_fees(gross)
        net_cents = fees["net_received"]
        profit_cents = net_cents - int((opt_buy * 100).to_integral_value())
        net = (Decimal(net_cents) / 100).quantize(Decimal("0.01"))
        profit = (Decimal(profit_cents) / 100).quantize(Decimal("0.01"))
        return net, profit

    @staticmethod
    def simulate_round_trips(
        records: List[PriceHistoryRecord], buy_target: Decimal, sell_target: Decimal
    ) -> Tuple[int, Optional[Decimal]]:
        """Replay the history the way the bot would trade it."""
        ordered = sorted(records, key=lambda r: r.recorded_at)
        holding = False
        entered_at = None
        trips = 0
        holds: List[float] = []

        for record in ordered:
            if not holding and record.price <= buy_target:
                holding, entered_at = True, record.recorded_at
            elif holding and record.price >= sell_target:
                holding = False
                trips += 1
                holds.append((record.recorded_at - entered_at).total_seconds() / 3600)

        if not holds:
            return trips, None
        return trips, Decimal(str(round(statistics.median(holds), 1)))

    @staticmethod
    def queue_ahead(sell_levels: List[dict], price: Optional[Decimal]) -> Optional[int]:
        """
        How many listings would be bought before ours.

        Steam serves the cheapest listing first, so everything priced at or below ours
        stands in front of it. The history says whether the price ever reaches our target;
        this says whether we would be the one who sells when it does.
        """
        if price is None or not sell_levels:
            return None
        return sum(
            level["quantity"] for level in sell_levels if level.get("price") is not None and level["price"] <= price
        )

    @staticmethod
    def days_to_clear(queue_ahead: Optional[int], daily_volume: Optional[Decimal]) -> Optional[Decimal]:
        """
        How long the queue in front of us takes to drain, at the recent rate of sales.

        A lower bound on the wait, and a loose one: cheaper listings keep arriving and
        push in front of us, while some of the volume is taken by buy orders that never
        touch the queue at all.
        """
        if queue_ahead is None or not daily_volume or daily_volume <= 0:
            return None
        return (Decimal(queue_ahead) / Decimal(daily_volume)).quantize(Decimal("0.1"))

    @staticmethod
    def feasible_round_trips(round_trips: int, days_to_clear: Optional[Decimal], window_days: int) -> int:
        """
        Trips the history allows, capped by how many the queue leaves time for.

        The simulation assumes a fill every time the price touches the target, which is
        the assumption that cost us money the one time we traded for real.
        """
        if days_to_clear is None or days_to_clear <= 0 or window_days <= 0:
            return round_trips
        return min(round_trips, int(Decimal(window_days) / days_to_clear))

    @classmethod
    def choose_sell_price(
        cls,
        records: List[PriceHistoryRecord],
        buy_target: Decimal,
        sell_levels: List[dict],
        daily_volume: Optional[Decimal],
        window_days: int,
        ceiling: int,
    ) -> Optional[SellChoice]:
        """
        Price the item at every level it actually trades at, and keep whichever pays best.

        Asking more earns more per sale but puts more sellers in front of us, and the two
        pull against each other. Where the balance falls depends on where the walls of
        listings sit in this item's own book, which is why one percentile cannot serve
        every item.
        """
        prices = [record.price for record in records]
        volumes = [record.volume for record in records]
        floor = minimum_listing_price()
        options: List[SellChoice] = []
        seen = set()

        for percentile in range(SELL_SEARCH_FLOOR, ceiling + 1):
            price = weighted_percentile(prices, volumes, percentile)
            if price < floor or price in seen:
                continue
            seen.add(price)

            trips, hold = cls.simulate_round_trips(records, buy_target, price)
            queue = cls.queue_ahead(sell_levels, price)
            wait = cls.days_to_clear(queue, daily_volume)
            options.append(
                SellChoice(
                    percentile=percentile,
                    price=price,
                    profit=(net_received(price) - buy_target).quantize(Decimal("0.01")),
                    round_trips=trips,
                    median_hold_hours=hold,
                    queue_ahead=queue,
                    days_to_clear=wait,
                    feasible_round_trips=cls.feasible_round_trips(trips, wait, window_days),
                )
            )

        if not options:
            return None
        return max(options, key=lambda option: (option.profit_per_window, option.profit))

    @staticmethod
    def project_return_on_capital(
        profit_per_trade: Decimal, round_trips: int, buy_target: Decimal, window_days: int
    ) -> Optional[Decimal]:
        """Return over the window, scaled to 30 days so the threshold means the same thing whichever analysis window is configured."""
        if buy_target <= 0 or window_days <= 0:
            return None

        over_window = profit_per_trade * round_trips / buy_target * 100
        return (over_window * Decimal(30) / Decimal(window_days)).quantize(Decimal("0.1"))

    async def evaluate(
        self,
        records: List[PriceHistoryRecord],
        current_price: Optional[Decimal],
        volume24h: Optional[int],
        sell_levels: List[dict],
        window_days: int,
    ) -> Evaluation:
        """
        The one judgement of an item, shared by the market scan and the pool.

        Two separate code paths would drift apart, and then the scan would recommend
        items the pool turns down for reasons nobody can see.
        """
        clean = self.filter_price_outliers(records)
        dropped = len(records) - len(clean)
        if len(clean) < 2:
            return Evaluation(False, "not enough price history", dropped)

        settings = await self.settings_service.get_settings()
        prices = [record.price for record in clean]
        volumes = [record.volume for record in clean]

        buy_target = weighted_percentile(prices, volumes, settings.buy_percentile)
        if buy_target <= 0:
            return Evaluation(False, "no usable buy target", dropped)

        daily_volume = Decimal(sum(volumes)) / window_days if window_days else None
        choice = self.choose_sell_price(
            clean, buy_target, sell_levels, daily_volume, window_days, settings.sell_percentile
        )
        if choice is None:
            return Evaluation(False, "no asking price Steam would accept", dropped, buy_target)

        volatility = await self.compute_volume_weighted_volatility(clean)
        _, volume7d = await self.compute_recent_stats(clean, WEEKLY_WINDOW)
        return_on_capital = self.project_return_on_capital(
            choice.profit, choice.feasible_round_trips, buy_target, window_days
        )

        tradable, reason = await self.decide_trade_flag(
            ItemIndicators(
                profit=choice.profit,
                volume24h=volume24h,
                volume7d=volume7d,
                volatility=volatility,
                round_trips=choice.round_trips,
                median_hold_hours=choice.median_hold_hours,
                return_on_capital_30d=return_on_capital,
            )
        )
        if tradable and not self.history_describes_current_market(clean, current_price):
            tradable, reason = False, "the price history is centred far from the current price"

        return Evaluation(
            tradable=tradable,
            reason=reason,
            outliers_dropped=dropped,
            buy_target=buy_target,
            choice=choice,
            volatility=volatility,
            volume7d=volume7d,
            return_on_capital_30d=return_on_capital,
        )

    async def decide_trade_flag(self, indicators: ItemIndicators) -> Tuple[bool, str]:
        """Whether the bot should trade this item, and why not when it should not."""
        settings = await self.settings_service.get_settings()

        if indicators.profit < settings.min_profit_threshold:
            return False, f"profit {indicators.profit} is below {settings.min_profit_threshold}"

        if indicators.volume24h is None or indicators.volume24h < settings.min_volume_24h:
            return False, f"volume over 24h {indicators.volume24h} is below {settings.min_volume_24h}"

        if indicators.volume7d is None or indicators.volume7d < settings.min_volume_7d:
            return False, f"volume over 7d {indicators.volume7d} is below {settings.min_volume_7d}"

        if indicators.volatility > settings.max_volatility_threshold:
            return False, f"volatility {indicators.volatility} is above {settings.max_volatility_threshold}"

        if indicators.round_trips < 1:
            return False, "the price never covered the whole range in the analysis window"

        if indicators.median_hold_hours is None or indicators.median_hold_hours > settings.max_hold_hours:
            return False, f"holding time {indicators.median_hold_hours} h is above {settings.max_hold_hours} h"

        if (
            indicators.return_on_capital_30d is None
            or indicators.return_on_capital_30d < settings.min_return_on_capital_30d
        ):
            return False, (
                f"return {indicators.return_on_capital_30d}% is below "
                f"{settings.min_return_on_capital_30d}% per 30 days"
            )

        return True, ""
