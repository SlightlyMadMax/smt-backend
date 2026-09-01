import argparse
import asyncio
import random
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import delete, select

from smt.db.database import async_session_maker
from smt.db.models import PoolItem, Position
from smt.schemas.position import PositionStatus
from smt.utils.steam import net_received


MARKER = "demo-"
WINDOW_DAYS = 30
SEED = 20260901

FILL_RATE = 0.75
STILL_WAITING_DAYS = 3
GROSS_OVER_NET = Decimal("1.15")
PROFIT_FLOOR_PCT = Decimal("0.01")
PERFORMANCE = [Decimal("1.35"), Decimal("0.80"), Decimal("1.10"), Decimal("-0.40"), Decimal("1.60"), Decimal("0.25")]


def demo_id() -> str:
    return f"{MARKER}{uuid.uuid4().hex[:12]}"


def jitter(value: Decimal, spread: Decimal, rng: random.Random) -> Decimal:
    factor = Decimal(str(rng.uniform(float(1 - spread), float(1 + spread))))
    return (value * factor).quantize(Decimal("0.01"))


def build_for_item(item: PoolItem, performance: Decimal, rng: random.Random, now: datetime) -> List[Position]:
    buy_target = item.optimal_buy_price or Decimal("5.00")
    hold_hours = float(item.median_hold_hours or 12)

    floor = (buy_target * PROFIT_FLOOR_PCT).quantize(Decimal("0.01"))
    target_profit = (max(item.potential_profit or Decimal("0"), floor) * performance).quantize(Decimal("0.01"))

    cycle_hours = max(hold_hours * 2.5, 6.0)
    attempts = max(2, min(14, int(WINDOW_DAYS * 24 / cycle_hours)))
    slot_hours = WINDOW_DAYS * 24 / attempts
    window_start = now - timedelta(days=WINDOW_DAYS)

    positions: List[Position] = []
    for n in range(attempts):
        opened_at = window_start + timedelta(
            hours=slot_hours * (n + 1) - rng.uniform(slot_hours * 0.1, slot_hours * 0.6)
        )
        buy_price = jitter(buy_target, Decimal("0.03"), rng)
        goal = target_profit + Decimal(str(round(rng.gauss(0, abs(float(target_profit)) * 0.8), 2)))
        sell_price = max(buy_price / GROSS_OVER_NET, (buy_price + goal) * GROSS_OVER_NET).quantize(Decimal("0.01"))

        if rng.random() > FILL_RATE:
            waiting = opened_at > now - timedelta(days=STILL_WAITING_DAYS)
            positions.append(
                Position(
                    pool_item_hash=item.market_hash_name,
                    buy_order_id=demo_id(),
                    buy_price=buy_price,
                    sell_price=sell_price,
                    status=PositionStatus.OPEN if waiting else PositionStatus.CANCELLED,
                    created_at=opened_at,
                    updated_at=opened_at if waiting else opened_at + timedelta(hours=min(cycle_hours, slot_hours)),
                )
            )
            continue

        bought_at = opened_at + timedelta(hours=rng.uniform(0.5, max(1.0, hold_hours / 2)))
        held = timedelta(hours=hold_hours * rng.uniform(0.6, 1.8))
        listed_at = bought_at + timedelta(minutes=rng.uniform(2, 30))
        sold_at = bought_at + held

        if sold_at >= now:
            positions.append(
                Position(
                    pool_item_hash=item.market_hash_name,
                    asset_id=demo_id(),
                    buy_order_id=demo_id(),
                    sell_order_id=demo_id(),
                    buy_price=buy_price,
                    sell_price=sell_price,
                    status=PositionStatus.LISTED,
                    bought_at=bought_at,
                    listed_at=listed_at,
                    created_at=opened_at,
                    updated_at=listed_at,
                )
            )
            continue

        proceeds = net_received(sell_price)
        positions.append(
            Position(
                pool_item_hash=item.market_hash_name,
                asset_id=demo_id(),
                buy_order_id=demo_id(),
                sell_order_id=demo_id(),
                buy_price=buy_price,
                sell_price=sell_price,
                net_proceeds=proceeds,
                realized_profit=proceeds - buy_price,
                status=PositionStatus.CLOSED,
                bought_at=bought_at,
                listed_at=listed_at,
                sold_at=sold_at,
                created_at=opened_at,
                updated_at=sold_at,
            )
        )

    return positions


async def clear(session) -> int:
    result = await session.execute(delete(Position).where(Position.buy_order_id.like(f"{MARKER}%")))
    await session.commit()
    return result.rowcount


async def seed(limit: Optional[int]) -> None:
    rng = random.Random(SEED)
    now = datetime.now(UTC)

    async with async_session_maker() as session:
        removed = await clear(session)
        if removed:
            print(f"Removed {removed} demo positions left over from a previous run.")

        items = list((await session.execute(select(PoolItem))).scalars().all())
        if limit:
            items = items[:limit]
        if not items:
            print("The pool is empty, so there is nothing to invent trades for.")
            return

        created = 0
        for index, item in enumerate(items):
            positions = build_for_item(item, PERFORMANCE[index % len(PERFORMANCE)], rng, now)
            session.add_all(positions)
            created += len(positions)
            print(f"{item.market_hash_name}: {len(positions)} positions")

        await session.commit()
        print(f"Added {created} demo positions across {len(items)} items.")


async def wipe() -> None:
    async with async_session_maker() as session:
        print(f"Removed {await clear(session)} demo positions.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Invent positions so the statistics page has something to show.")
    parser.add_argument("--clear", action="store_true", help="remove the demo positions and stop")
    parser.add_argument("--items", type=int, default=None, help="only use the first N pool items")
    args = parser.parse_args()

    asyncio.run(wipe() if args.clear else seed(args.items))


if __name__ == "__main__":
    main()
