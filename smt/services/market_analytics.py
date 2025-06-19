import math
from decimal import Decimal
from typing import List, Optional, Tuple

from smt.db.models import PriceHistoryRecord
from smt.utils.math import weighted_percentile
from smt.utils.steam import calculate_fees


class MarketAnalyticsService:
    @staticmethod
    def compute_weighted_percentile_targets(
        records: List[PriceHistoryRecord], buy_pct: int, sell_pct: int
    ) -> Tuple[Decimal, Decimal]:
        prices = [float(r.price) for r in records]
        vols = [r.volume for r in records]
        buy = weighted_percentile(prices, vols, buy_pct)
        sell = weighted_percentile(prices, vols, sell_pct)
        return buy, sell

    @staticmethod
    def compute_volume_weighted_volatility(records: List[PriceHistoryRecord]) -> Decimal:
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
    def compute_net_and_profit(opt_sell: Decimal, opt_buy: Decimal) -> Tuple[Decimal, Decimal]:
        gross = int((opt_sell * 100).to_integral_value())
        fees = calculate_fees(gross)
        net_cents = fees["net_received"]
        profit_cents = net_cents - int((opt_buy * 100).to_integral_value())
        net = (Decimal(net_cents) / 100).quantize(Decimal("0.01"))
        profit = (Decimal(profit_cents) / 100).quantize(Decimal("0.01"))
        return net, profit

    @staticmethod
    def decide_trade_flag(profit: Decimal, volume24h: Optional[int]) -> bool:
        return bool(profit > Decimal("0.10") and volume24h is not None and volume24h > 10)
