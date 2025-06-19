from decimal import Decimal
from typing import List


def weighted_percentile(prices: List[float], volumes: List[int], pct: float) -> Decimal:
    """
    Return the price at which the cumulative volume reaches pct% of total.
    """
    pv = sorted(zip(prices, volumes), key=lambda x: x[0])
    total_vol = sum(volumes)
    cutoff = total_vol * (pct / 100)
    cum = 0
    for price, vol in pv:
        cum += vol
        if cum >= cutoff:
            return Decimal(price).quantize(Decimal("0.01"))
    return Decimal(pv[-1][0]).quantize(Decimal("0.01"))
