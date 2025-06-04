from sqlalchemy.exc import NoResultFound
from steampy.models import GameOptions

from smt.repositories.pool_items import PoolRepo
from smt.schemas.pool import PoolItemUpdate
from smt.schemas.price_history import PriceHistoryRecordCreate
from smt.services.price_history import PriceHistoryService
from smt.services.steam import SteamService


async def backfill_price_history_for(
    pool_repo: PoolRepo,
    steam: SteamService,
    price_history_service: PriceHistoryService,
    market_hash_names: list[str],
):
    records: list[PriceHistoryRecordCreate] = []

    for market_hash_name in market_hash_names:
        try:
            pool_item = await pool_repo.get_by_market_hash_name(market_hash_name)
        except NoResultFound:
            continue

        game_opt = GameOptions(pool_item.app_id, pool_item.context_id)
        raw_hist = steam.get_price_history(market_hash_name, game_opt)
        for ts, price, vol in raw_hist:
            records.append(
                PriceHistoryRecordCreate(
                    market_hash_name=market_hash_name,
                    recorded_at=ts,
                    price=price,
                    volume=vol,
                )
            )

    if records:
        await price_history_service.add_many(records)


async def update_snapshot_for(pool_repo: PoolRepo, steam: SteamService, market_hash_name: str):
    try:
        pool_item = await pool_repo.get_by_market_hash_name(market_hash_name)
    except NoResultFound:
        return

    game_opt = GameOptions(pool_item.app_id, pool_item.context_id)
    snap = steam.get_price(market_hash_name, game_opt)
    update_payload = PoolItemUpdate(
        current_lowest=snap["lowest_price"],
        current_median=snap["median_price"],
        current_volume24h=snap["volume"],
    )
    await pool_repo.update(market_hash_name, update_payload)
