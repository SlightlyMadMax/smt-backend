import math
import statistics
from datetime import timedelta
from decimal import Decimal
from typing import List, Optional, Tuple

from smt.db.models import PriceHistoryRecord
from smt.services.settings import SettingsService
from smt.utils.math import weighted_percentile
from smt.utils.steam import calculate_fees


OUTLIER_PRICE_FACTOR = Decimal("5")


class MarketAnalyticsService:
    def __init__(self, settings_service: SettingsService):
        self.settings_service = settings_service

    @staticmethod
    def filter_price_outliers(
        records: List[PriceHistoryRecord], factor: Decimal = OUTLIER_PRICE_FACTOR
    ) -> List[PriceHistoryRecord]:
        """
        Drop records whose price is more than `factor` times away from the median.

        Steam price history occasionally contains points one or two orders of magnitude
        off the real price, which distorts volatility far more than it distorts a volume
        weighted percentile.
        """
        if not records:
            return []

        median = statistics.median(r.price for r in records)
        if median <= 0:
            return list(records)

        low, high = median / factor, median * factor
        return [r for r in records if low <= r.price <= high]

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
        """
        Return the volume weighted median price and the traded volume within `window`.

        The window ends at the newest record rather than at the current time, because
        Steam publishes price history with a lag. Records are hourly buckets and the
        bound is exclusive, so a 24 hour window covers 24 buckets, not 25.
        """
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

    async def decide_trade_flag(self, profit: Decimal, volume24h: Optional[int], volatility: Decimal) -> bool:
        settings = await self.settings_service.get_settings()

        if profit < settings.min_profit_threshold:
            return False

        if volume24h is None or volume24h < settings.min_volume_24h:
            return False

        if volatility < settings.min_volatility_threshold or volatility > settings.max_volatility_threshold:
            return False

        return True
