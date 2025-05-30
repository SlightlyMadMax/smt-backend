def transform_inventory_item(item: dict) -> dict:
    return {
        "id": item["id"],
        "name": item["name"],
        "market_hash_name": item["market_hash_name"],
        "tradable": item["tradable"],
        "marketable": item["marketable"],
        "amount": item["amount"],
        "icon_url": f"https://steamcommunity-a.akamaihd.net/economy/image/{item['icon_url']}",
    }
