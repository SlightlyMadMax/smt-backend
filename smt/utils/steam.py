import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_DOWN, Decimal
from typing import Optional, Tuple

from smt.logger import get_logger


logger = get_logger("utils.steam")


@dataclass(frozen=True)
class FeeSchedule:
    """Steam's market fee parameters, as published in g_rgWalletInfo."""

    steam_percent: Decimal = Decimal("0.05")
    publisher_percent: Decimal = Decimal("0.10")
    minimum: int = 86
    base: int = 0


_schedule = FeeSchedule()


def get_fee_schedule() -> FeeSchedule:
    return _schedule


def set_fee_schedule(schedule: FeeSchedule) -> None:
    global _schedule
    if schedule != _schedule:
        logger.info(f"Steam fee schedule is now {schedule}.")
    _schedule = schedule


def transform_inventory_item(item: dict) -> dict:
    return {
        "id": item["id"],
        "name": item["name"],
        "market_hash_name": item["market_hash_name"],
        "tradable": int(item.get("tradable", 0)),
        "marketable": int(item.get("marketable", 0)),
        "icon_url": f"https://steamcommunity-a.akamaihd.net/economy/image/{item['icon_url']}",
    }


def parse_steam_ts(ts: str) -> datetime:
    # Remove the "+0" or "+X" suffix (Steam includes this, but it's broken)
    ts = re.sub(r"\s[+-]\d+$", "", ts)

    # Fix malformed time like "01:" → "01:00"
    if re.match(r".*\d{2}:$", ts):
        ts += "00"

    dt = datetime.strptime(ts, "%b %d %Y %H:%M")
    return dt.replace(tzinfo=timezone.utc)


def _floor_fee(amount: int, pct: Decimal, minimum: int, base: int = 0) -> int:
    """
    floor(max(amount * pct, minimum) + base)
    """
    raw = max(Decimal(amount) * pct, Decimal(minimum)) + base
    return int(raw.to_integral_value(rounding=ROUND_DOWN))


def _calculate_for_received(received: int, schedule: FeeSchedule) -> Tuple[int, int, int]:
    """
    Given a candidate 'received', return a tuple of
      (steam_fee, publisher_fee, total_amount_sent).
    """
    steam_fee = _floor_fee(received, schedule.steam_percent, schedule.minimum, schedule.base)
    publisher_fee = _floor_fee(received, schedule.publisher_percent, schedule.minimum, 0)
    total_sent = received + steam_fee + publisher_fee
    return steam_fee, publisher_fee, total_sent


def calculate_fees(gross: int, schedule: Optional[FeeSchedule] = None) -> dict:
    """
    Given gross (what buyer pays, in cents/kopecks), returns:
      - steam_fee (int)
      - publisher_fee (int)
      - total_fees (int)
      - net_received (int)
    following Steam’s logic.
    """
    schedule = schedule or _schedule
    estimated_received = int((gross - schedule.base) / (1 + schedule.steam_percent + schedule.publisher_percent))

    has_ever_undershot = False
    steam_fee, publisher_fee, amount_sent = _calculate_for_received(estimated_received, schedule)

    # 2) iterate up/down up to 10x, like Steam’s JS
    iterations = 0
    while amount_sent != gross and iterations < 10:
        if amount_sent > gross:
            if has_ever_undershot:
                # apply last‑cent patch at estimated_received−1
                sf2, pf2, sent2 = _calculate_for_received(estimated_received - 1, schedule)
                diff = gross - sent2
                sf2 += diff
                sent2 = gross
                steam_fee, publisher_fee, amount_sent = sf2, pf2, sent2
                break
            else:
                estimated_received -= 1
        else:
            has_ever_undershot = True
            estimated_received += 1

        steam_fee, publisher_fee, amount_sent = _calculate_for_received(estimated_received, schedule)
        iterations += 1

    total_fees = steam_fee + publisher_fee
    net_received = gross - total_fees

    return {
        "steam_fee": steam_fee,
        "publisher_fee": publisher_fee,
        "total_fees": total_fees,
        "net_received": net_received,
    }


def minimum_listing_price(schedule: Optional[FeeSchedule] = None) -> Decimal:
    """
    The cheapest listing Steam accepts.

    Both fees bottom out at the same minimum, and the seller cannot receive less than it
    either, so the floor is three of them.
    """
    schedule = schedule or _schedule
    return (Decimal(schedule.minimum * 3 + schedule.base) / 100).quantize(Decimal("0.01"))


def net_received(gross: Decimal) -> Decimal:
    """What the seller receives after fees when the buyer pays `gross`."""
    kopecks = int((gross * 100).to_integral_value())
    return (Decimal(calculate_fees(kopecks)["net_received"]) / 100).quantize(Decimal("0.01"))
