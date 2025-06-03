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
