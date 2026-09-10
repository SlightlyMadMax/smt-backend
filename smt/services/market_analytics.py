import math
import statistics
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import List, Optional, Tuple

from smt.db.models import PriceHistoryRecord
from smt.services.settings import SettingsService
from smt.utils.math import weighted_percentile
from smt.utils.steam import calculate_fees


OUTLIER_PRICE_FACTOR = Decimal("5")


@dataclass
class ItemIndicators:
    profit: Decimal
    profit_pct: Optional[Decimal]
    volume24h: Optional[int]
    volume7d: Optional[int]
    volatility: Decimal
    round_trips: int
    median_hold_hours: Optional[Decimal]
    return_on_capital_30d: Optional[Decimal]


PRICE_DRIFT_FACTOR = Decimal("2")


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

    @staticmethod
    def project_return_on_capital(
        profit_per_trade: Decimal, round_trips: int, buy_target: Decimal, window_days: int
    ) -> Optional[Decimal]:
        """Return over the window, scaled to 30 days so the threshold means the same thing whichever analysis window is configured."""
        if buy_target <= 0 or window_days <= 0:
            return None

        over_window = profit_per_trade * round_trips / buy_target * 100
        return (over_window * Decimal(30) / Decimal(window_days)).quantize(Decimal("0.1"))

    async def decide_trade_flag(self, indicators: ItemIndicators) -> Tuple[bool, str]:
        """Whether the bot should trade this item, and why not when it should not."""
        settings = await self.settings_service.get_settings()

        if indicators.profit < settings.min_profit_threshold:
            return False, f"profit {indicators.profit} is below {settings.min_profit_threshold}"

        if indicators.profit_pct is None or indicators.profit_pct < settings.min_profit_percentage:
            return False, f"margin {indicators.profit_pct}% is below {settings.min_profit_percentage}%"

        if indicators.volume24h is None or indicators.volume24h < settings.min_volume_24h:
            return False, f"volume over 24h {indicators.volume24h} is below {settings.min_volume_24h}"

        if indicators.volume7d is None or indicators.volume7d < settings.min_volume_7d:
            return False, f"volume over 7d {indicators.volume7d} is below {settings.min_volume_7d}"

        if indicators.volatility < settings.min_volatility_threshold:
            return False, f"volatility {indicators.volatility} is below {settings.min_volatility_threshold}"

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
