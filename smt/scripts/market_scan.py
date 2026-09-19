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
import sys
from dataclasses import fields
from decimal import Decimal
from typing import List, Optional

from smt.core.config import get_settings
from smt.db.database import async_session_maker
from smt.repositories.settings import SettingsRepo
from smt.services.market_analytics import MarketAnalyticsService
from smt.services.market_scan import Candidate, MarketScanService, ScanParams
from smt.services.settings import SettingsService
from smt.services.steam import SteamService


def report(candidates: List[Candidate], out_path: Optional[str]) -> None:
    measured = [c for c in candidates if c.sell_target is not None]
    rejected = [c for c in candidates if not c.tradable]
    measured.sort(key=lambda c: (c.return_on_capital_pct or Decimal("-999")), reverse=True)
    tradable = [c for c in candidates if c.tradable]

    if rejected:
        print(f"\n{len(rejected)} items the pool would turn down, e.g.")
        for c in rejected[:5]:
            print(f"   {c.market_hash_name[:50]:<52} {c.note}")

    if not measured:
        print("\nnothing measured")
        return

    share = len(tradable) / len(measured) * 100
    print(f"\nmeasured {len(measured)} items, the pool would trade {len(tradable)} ({share:.1f}%)")

    header = (
        f"{'item':<38}{'buy':>7}{'sell':>7}{'volume':>8}"
        f"{'trips':>6}{'hold h':>8}{'per trip':>9}{'window':>8}{'ROI':>8}"
    )
    print("\n" + header)
    for c in measured[:30]:
        name = c.market_hash_name.encode("ascii", "replace").decode()[:39]
        hold = c.median_hold_hours if c.median_hold_hours is not None else "-"
        print(
            f"{name[:37]:<38}{c.buy_target:>7}{c.sell_target:>7}{c.volume_window:>8}"
            f"{c.feasible_round_trips:>6}{hold:>8}{c.profit_per_trade:>9}{c.profit_per_window:>8}"
            f"{c.return_on_capital_pct:>7}%"
        )

    if out_path:
        with open(out_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow([f.name for f in fields(Candidate)])
            for c in candidates:
                writer.writerow([getattr(c, f.name) for f in fields(Candidate)])
        print(f"\nwrote {len(candidates)} rows to {out_path}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--app-id", default="440", help="Steam app id, 440 is TF2")
    parser.add_argument("--context-id", default="2")
    parser.add_argument("--limit", type=int, default=50, help="how many items to measure")
    parser.add_argument("--min-price", type=Decimal, default=Decimal("1.00"))
    parser.add_argument("--max-price", type=Decimal, default=Decimal("100.00"))
    parser.add_argument("--out", help="write the full result to this CSV")
    args = parser.parse_args()

    steam = SteamService(get_settings())
    params = ScanParams(
        app_id=args.app_id,
        context_id=args.context_id,
        limit=args.limit,
        min_price=args.min_price,
        max_price=args.max_price,
    )

    async with async_session_maker() as session:
        settings_service = SettingsService(SettingsRepo(session))
        service = MarketScanService(steam, steam._redis, MarketAnalyticsService(settings_service), settings_service)

        scan_id = service.new_id()
        print(f"scan {scan_id} for app {args.app_id} priced {args.min_price}..{args.max_price}", file=sys.stderr)
        await service.run(scan_id, params)

        state = await service.get(scan_id)
        if state and state["status"] == "failed":
            print(f"scan failed: {state['error']}", file=sys.stderr)

        report(await _candidates(service, scan_id), args.out)

    await steam._redis.aclose()


async def _candidates(service: MarketScanService, scan_id: str) -> List[Candidate]:
    state = await service.get(scan_id)
    if not state:
        return []
    return [_from_row(row) for row in state["candidates"]]


def _from_row(row: dict) -> Candidate:
    decimals = {
        "current_price",
        "buy_target",
        "sell_target",
        "spread_pct",
        "required_pct",
        "profit_per_trade",
        "median_hold_hours",
        "profit_per_window",
        "return_on_capital_pct",
        "median_price",
        "price_drift",
    }
    values = {k: (Decimal(v) if k in decimals and v is not None else v) for k, v in row.items()}
    return Candidate(**values)


if __name__ == "__main__":
    asyncio.run(main())
