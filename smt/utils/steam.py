import re
from datetime import datetime, timezone
from decimal import ROUND_DOWN, Decimal
from typing import Tuple

from smt.logger import get_logger


logger = get_logger("utils.steam")


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


def _calculate_for_received(
    received: int, steam_fee_pct: Decimal, steam_fee_min: int, steam_fee_base: int, publisher_fee_pct: Decimal
) -> Tuple[int, int, int]:
    """
    Given a candidate 'received', return a tuple of
      (steam_fee, publisher_fee, total_amount_sent).
    """
    steam_fee = _floor_fee(received, steam_fee_pct, steam_fee_min, steam_fee_base)
    publisher_fee = _floor_fee(received, publisher_fee_pct, 1, 0)
    total_sent = received + steam_fee + publisher_fee
    return steam_fee, publisher_fee, total_sent


def calculate_fees(
    gross: int,
    steam_fee_percent: Decimal = Decimal("0.05"),
    steam_fee_minimum: int = 1,
    steam_fee_base: int = 0,
    publisher_fee_percent: Decimal = Decimal("0.10"),
) -> dict:
    """
    Given gross (what buyer pays, in cents/kopecks), returns:
      - steam_fee (int)
      - publisher_fee (int)
      - total_fees (int)
      - net_received (int)
    following Steam’s logic.
    """
    estimated_received = int((gross - steam_fee_base) / (1 + steam_fee_percent + publisher_fee_percent))

    has_ever_undershot = False
    steam_fee, publisher_fee, amount_sent = _calculate_for_received(
        estimated_received, steam_fee_percent, steam_fee_minimum, steam_fee_base, publisher_fee_percent
    )

    # 2) iterate up/down up to 10x, like Steam’s JS
    iterations = 0
    while amount_sent != gross and iterations < 10:
        if amount_sent > gross:
            if has_ever_undershot:
                # apply last‑cent patch at estimated_received−1
                sf2, pf2, sent2 = _calculate_for_received(
                    estimated_received - 1, steam_fee_percent, steam_fee_minimum, steam_fee_base, publisher_fee_percent
                )
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

        steam_fee, publisher_fee, amount_sent = _calculate_for_received(
            estimated_received, steam_fee_percent, steam_fee_minimum, steam_fee_base, publisher_fee_percent
        )
        iterations += 1

    total_fees = steam_fee + publisher_fee
    net_received = gross - total_fees

    return {
        "steam_fee": steam_fee,
        "publisher_fee": publisher_fee,
        "total_fees": total_fees,
        "net_received": net_received,
    }
