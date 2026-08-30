"""
Rank market items by how well they suit the trading strategy.

Steam charges its fee on what the seller receives, so a round trip only breaks even
once the sell price is about 15% above the buy price. This script measures, for each
candidate item, whether its own price distribution is wide enough to clear that.

Run it with, for example:

    python -m smt.scripts.market_scan --app-id 440 --limit 100 --out tf2.csv
"""

import argparse
import asyncio
import csv
import statistics
import sys
from dataclasses import dataclass, fields
from decimal import Decimal
from typing import List, Optional

from steampy.models import GameOptions

from smt.core.config import get_settings
from smt.services.market_analytics import OUTLIER_PRICE_FACTOR
from smt.services.steam import SteamService
from smt.utils.math import weighted_percentile
from smt.utils.steam import net_received


PAGE_SIZE = 100


@dataclass
class Candidate:
    market_hash_name: str
    listings: int
    current_price: Decimal
    volume_30d: int = 0
    buy_target: Optional[Decimal] = None
    sell_target: Optional[Decimal] = None
    spread_pct: Optional[Decimal] = None
    required_pct: Optional[Decimal] = None
    profit_per_trade: Optional[Decimal] = None
    round_trips: int = 0
    profit_per_window: Optional[Decimal] = None
    median_price: Optional[Decimal] = None
    price_drift: Optional[Decimal] = None
    tradable: bool = False
    note: str = ""


def required_spread_pct(buy: Decimal) -> Decimal:
    """How far above `buy` the sell price must sit for the round trip to break even."""
    sell = buy
    step = Decimal("0.01")
    while net_received(sell) < buy:
        sell += step
    return ((sell / buy - 1) * 100).quantize(Decimal("0.01"))


def drop_outliers(points: List[tuple]) -> List[tuple]:
    if not points:
        return []
    median = statistics.median(price for _, price, _ in points)
    if median <= 0:
        return points
    low, high = median / OUTLIER_PRICE_FACTOR, median * OUTLIER_PRICE_FACTOR
    return [p for p in points if low <= p[1] <= high]


async def collect_candidates(
    steam: SteamService, app_id: str, wanted: int, min_price: Decimal, max_price: Decimal
) -> List[Candidate]:
    candidates: List[Candidate] = []
    start = 0

    while len(candidates) < wanted:
        page = await steam.search_market(app_id=app_id, start=start, count=PAGE_SIZE)
        results = page.get("results") or []
        if not results:
            break

        for row in results:
            price = Decimal(row.get("sell_price", 0)) / 100
            if not (min_price <= price <= max_price):
                continue
            candidates.append(
                Candidate(
                    market_hash_name=row["hash_name"],
                    listings=int(row.get("sell_listings") or 0),
                    current_price=price,
                )
            )
            if len(candidates) >= wanted:
                break

        start += PAGE_SIZE
        print(f"  scanned {start} listings, {len(candidates)} candidates in the price band", file=sys.stderr)
        if start >= int(page.get("total_count") or 0):
            break

    return candidates


def count_round_trips(points: List[tuple], buy_target: Decimal, sell_target: Decimal) -> int:
    """
    How many times the price fell to the buy target and then rose to the sell target.

    Fills are assumed at the targets themselves, because that is where the bot's limit
    orders sit; entering at the extreme of a dip would flatter the result.
    """
    holding = False
    trips = 0
    for _, price, _ in points:
        if not holding and price <= buy_target:
            holding = True
        elif holding and price >= sell_target:
            holding = False
            trips += 1
    return trips


async def measure(
    steam: SteamService,
    candidate: Candidate,
    app_id: str,
    days: int,
    buy_pct: int,
    sell_pct: int,
    max_drift: Decimal,
) -> Candidate:
    history = await steam.get_price_history(
        market_hash_name=candidate.market_hash_name,
        game=GameOptions(app_id, "2"),
        days=days,
    )
    points = drop_outliers(history)
    if len(points) < 2:
        candidate.note = "not enough history"
        return candidate

    candidate.volume_30d = sum(volume for _, _, volume in points)
    candidate.median_price = statistics.median(price for _, price, _ in points)

    # A history centred far away from today's asking price does not describe what can
    # be bought now, whatever the reason, so the percentiles taken from it are useless.
    if candidate.current_price > 0:
        candidate.price_drift = (candidate.median_price / candidate.current_price).quantize(Decimal("0.01"))
        if not (1 / max_drift <= candidate.price_drift <= max_drift):
            candidate.note = f"history is {candidate.price_drift}x the current price"
            return candidate

    prices = [price for _, price, _ in points]
    volumes = [volume for _, _, volume in points]
    candidate.buy_target = weighted_percentile(prices, volumes, buy_pct)
    candidate.sell_target = weighted_percentile(prices, volumes, sell_pct)

    if candidate.buy_target <= 0:
        candidate.note = "no usable buy target"
        return candidate

    candidate.spread_pct = ((candidate.sell_target / candidate.buy_target - 1) * 100).quantize(Decimal("0.01"))
    candidate.required_pct = required_spread_pct(candidate.buy_target)
    candidate.profit_per_trade = (net_received(candidate.sell_target) - candidate.buy_target).quantize(Decimal("0.01"))
    candidate.tradable = candidate.profit_per_trade > 0

    candidate.round_trips = count_round_trips(points, candidate.buy_target, candidate.sell_target)
    candidate.profit_per_window = (candidate.profit_per_trade * candidate.round_trips).quantize(Decimal("0.01"))
    return candidate


def report(candidates: List[Candidate], out_path: Optional[str]) -> None:
    measured = [c for c in candidates if c.spread_pct is not None]
    rejected = [c for c in candidates if c.spread_pct is None and c.note]
    measured.sort(key=lambda c: (c.profit_per_window or Decimal("-999")), reverse=True)
    tradable = [c for c in measured if c.tradable]

    if rejected:
        print(f"\nskipped {len(rejected)} items whose history does not describe a single good, e.g.")
        for c in rejected[:5]:
            print(f"   {c.market_hash_name[:50]:<52} {c.note}")

    if not measured:
        print("\nnothing measured")
        return

    share = len(tradable) / len(measured) * 100
    print(f"\nmeasured {len(measured)} items, {len(tradable)} clear the fee hurdle ({share:.1f}%)")

    header = f"{'item':<40}{'price':>8}{'vol30d':>8}{'buy':>8}{'sell':>8}" f"{'per trip':>10}{'trips':>7}{'per 30d':>9}"
    print("\n" + header)
    for c in measured[:30]:
        name = c.market_hash_name.encode("ascii", "replace").decode()[:39]
        print(
            f"{name:<40}{c.current_price:>8}{c.volume_30d:>8}"
            f"{c.buy_target:>8}{c.sell_target:>8}{c.profit_per_trade:>10}{c.round_trips:>7}{c.profit_per_window:>9}"
        )

    if out_path:
        with open(out_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow([f.name for f in fields(Candidate)])
            for c in measured + rejected:
                writer.writerow([getattr(c, f.name) for f in fields(Candidate)])
        print(f"\nwrote {len(measured) + len(rejected)} rows to {out_path}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--app-id", default="440", help="Steam app id, 440 is TF2")
    parser.add_argument("--limit", type=int, default=50, help="how many items to measure")
    parser.add_argument("--days", type=int, default=30, help="price history window")
    parser.add_argument("--buy-pct", type=int, default=10, help="percentile used as the buy target")
    parser.add_argument("--sell-pct", type=int, default=90, help="percentile used as the sell target")
    parser.add_argument("--min-price", type=Decimal, default=Decimal("1.00"))
    parser.add_argument("--max-price", type=Decimal, default=Decimal("100.00"))
    parser.add_argument("--min-volume", type=int, default=100, help="minimum traded volume over the window")
    parser.add_argument(
        "--max-drift",
        type=Decimal,
        default=Decimal("2"),
        help="reject an item when its median historical price differs from today's by more than this factor",
    )
    parser.add_argument("--out", help="write the full result to this CSV")
    args = parser.parse_args()

    steam = SteamService(get_settings())

    print(f"collecting candidates for app {args.app_id} " f"priced {args.min_price}..{args.max_price}", file=sys.stderr)
    candidates = await collect_candidates(steam, args.app_id, args.limit, args.min_price, args.max_price)
    print(f"measuring {len(candidates)} items (rate limited, expect a few minutes)", file=sys.stderr)

    measured = []
    for index, candidate in enumerate(candidates, start=1):
        try:
            measured.append(
                await measure(steam, candidate, args.app_id, args.days, args.buy_pct, args.sell_pct, args.max_drift)
            )
        except Exception as e:
            print(
                f"  [{index}/{len(candidates)}] {candidate.market_hash_name}: {type(e).__name__}: {e}", file=sys.stderr
            )
            continue
        print(f"  [{index}/{len(candidates)}] {candidate.market_hash_name}", file=sys.stderr)

    report([c for c in measured if c.volume_30d >= args.min_volume or c.note], args.out)


if __name__ == "__main__":
    asyncio.run(main())
