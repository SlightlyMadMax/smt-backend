import statistics as stats
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Sequence

from smt.db.models import Position
from smt.repositories.position import PositionRepo
from smt.schemas.position import PositionStatus


DEFAULT_TOP = 50
DEFAULT_DAYS = 30
NORMALISED_DAYS = Decimal(30)
MIN_TRADES_FOR_RETURN = 3
MIN_OBSERVATION_DAYS = Decimal(7)


def _percent(part: int, whole: int) -> Optional[Decimal]:
    if whole <= 0:
        return None
    return (Decimal(part) / Decimal(whole) * 100).quantize(Decimal("0.1"))


def _median_hours(positions: Sequence[Position], start: str, end: str) -> Optional[Decimal]:
    spans = [
        max(0.0, (getattr(p, end) - getattr(p, start)).total_seconds() / 3600)
        for p in positions
        if getattr(p, start) and getattr(p, end)
    ]
    if not spans:
        return None
    return Decimal(str(round(stats.median(spans), 1)))


def _forecast(values, how, places: str) -> Optional[Decimal]:
    """Forecasts recorded on the positions; trades opened before they were recorded have none."""
    present = [Decimal(value) for value in values if value is not None]
    if not present:
        return None
    return Decimal(how(present)).quantize(Decimal(places))


def _observed_days(positions: Sequence[Position]) -> Optional[Decimal]:
    """How long the item has actually been trading, from the first purchase to the last sale."""
    starts = [p.bought_at for p in positions if p.bought_at]
    ends = [p.sold_at for p in positions if p.sold_at]
    if not starts or not ends:
        return None

    return Decimal(str(round((max(ends) - min(starts)).total_seconds() / 86400, 1)))


def _return_30d(profit: Decimal, capital: Decimal, trades: int, observed_days: Optional[Decimal]) -> Optional[Decimal]:
    """
    Profit per unit of capital, scaled to 30 days so it lines up with the forecast.

    Scaling a short run up to 30 days multiplies its noise as well, so a run that is
    too short or too sparse gets no number at all.
    """
    if capital <= 0 or observed_days is None:
        return None
    if trades < MIN_TRADES_FOR_RETURN or observed_days < MIN_OBSERVATION_DAYS:
        return None

    return (profit / capital * 100 * NORMALISED_DAYS / observed_days).quantize(Decimal("0.1"))


class StatisticsService:
    """Aggregates closed positions into per item performance the position list cannot show."""

    def __init__(self, repo: PositionRepo):
        self.repo = repo

    async def overview(self, top: int = DEFAULT_TOP, days: int = DEFAULT_DAYS) -> dict:
        positions = await self.repo.list()
        closed = [p for p in positions if p.status == PositionStatus.CLOSED and p.realized_profit is not None]

        return {
            "funnel": self._funnel(positions),
            "items": self._by_item(closed)[:top],
            "daily_profit": self._daily_profit(closed, days),
        }

    @staticmethod
    def _funnel(positions: Sequence[Position]) -> dict:
        opened = len(positions)
        bought = sum(1 for p in positions if p.bought_at is not None)
        sold = sum(1 for p in positions if p.sold_at is not None)

        return {
            "opened": opened,
            "bought": bought,
            "sold": sold,
            "cancelled": sum(1 for p in positions if p.status == PositionStatus.CANCELLED),
            "fill_rate": _percent(bought, opened),
            "sell_through": _percent(sold, bought),
        }

    @staticmethod
    def _by_item(closed: Sequence[Position]) -> List[dict]:
        groups: Dict[str, List[Position]] = {}
        for position in closed:
            groups.setdefault(position.pool_item_hash, []).append(position)

        rows = []
        for market_hash_name, group in groups.items():
            item = group[0].pool_item
            profit = sum((p.realized_profit for p in group), Decimal(0))
            capital = sum((p.buy_price for p in group), Decimal(0)) / len(group)
            observed_days = _observed_days(group)

            rows.append(
                {
                    "market_hash_name": market_hash_name,
                    "name": item.name if item else market_hash_name,
                    "icon_url": item.icon_url if item else "",
                    "trades": len(group),
                    "profit": profit.quantize(Decimal("0.01")),
                    "avg_profit": (profit / len(group)).quantize(Decimal("0.01")),
                    "capital": capital.quantize(Decimal("0.01")),
                    "median_hold_hours": _median_hours(group, "bought_at", "sold_at"),
                    "sell_wait_hours": _median_hours(group, "listed_at", "sold_at"),
                    "buy_wait_hours": _median_hours(group, "created_at", "bought_at"),
                    "observed_days": observed_days,
                    "actual_return_30d": _return_30d(profit, capital, len(group), observed_days),
                    "forecast_profit": _forecast((p.forecast_profit for p in group), stats.mean, "0.01"),
                    "forecast_hold_hours": _forecast((p.forecast_hold_hours for p in group), stats.median, "0.1"),
                    "forecast_sell_wait_hours": _forecast(
                        (
                            p.forecast_days_to_clear * 24 if p.forecast_days_to_clear is not None else None
                            for p in group
                        ),
                        stats.median,
                        "0.1",
                    ),
                    "forecast_return_30d": _forecast((p.forecast_return_30d for p in group), stats.mean, "0.1"),
                }
            )

        rows.sort(key=lambda row: row["profit"], reverse=True)
        return rows

    @staticmethod
    def _daily_profit(closed: Sequence[Position], days: int) -> List[dict]:
        cutoff = (datetime.now(UTC) - timedelta(days=days)).date()
        totals: Dict[object, Decimal] = {}

        for position in closed:
            if not position.sold_at:
                continue
            day = position.sold_at.date()
            if day < cutoff:
                continue
            totals[day] = totals.get(day, Decimal(0)) + position.realized_profit

        return [{"day": day, "profit": totals[day].quantize(Decimal("0.01"))} for day in sorted(totals)]
