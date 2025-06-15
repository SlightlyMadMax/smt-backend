import re
from datetime import datetime, timezone
from decimal import ROUND_DOWN, Decimal


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
    # Estimate how much the seller should receive before fees
    estimated_received = int((gross - steam_fee_base) / (1 + steam_fee_percent + publisher_fee_percent))

    # Try small adjustments around the estimate
    for delta in range(-2, 3):
        received = estimated_received + delta
        # Steam fee: floor(max(received * pct, minimum) + base)
        steam_fee = int(
            (max(Decimal(received) * steam_fee_percent, Decimal(steam_fee_minimum)) + steam_fee_base).to_integral_value(
                rounding=ROUND_DOWN
            )
        )
        # Publisher fee: floor(max(received * pct, 1))
        publisher_fee = int(
            max(Decimal(received) * publisher_fee_percent, Decimal(1.0)).to_integral_value(rounding=ROUND_DOWN)
        )

        if received + steam_fee + publisher_fee == gross:
            return {
                "steam_fee": steam_fee,
                "publisher_fee": publisher_fee,
                "total_fees": steam_fee + publisher_fee,
                "net_received": received,
            }

    # Fallback if nothing matched exactly
    return {"steam_fee": 0, "publisher_fee": 0, "total_fees": 0, "net_received": 0}
