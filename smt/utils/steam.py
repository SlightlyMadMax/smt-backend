import re
from datetime import datetime, timezone


def transform_inventory_item(item: dict) -> dict:
    return {
        "id": item["id"],
        "name": item["name"],
        "market_hash_name": item["market_hash_name"],
        "tradable": int(item.get("tradable", 0)),
        "marketable": int(item.get("marketable", 0)),
        "amount": int(item.get("amount", 1)),
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
