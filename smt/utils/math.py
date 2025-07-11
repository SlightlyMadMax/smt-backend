from decimal import ROUND_HALF_UP, Decimal
from typing import List


def weighted_percentile(prices: List[Decimal], volumes: List[int], pct: int) -> Decimal:
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
            return price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    # Fallback to the highest price
    return pv[-1][0].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
