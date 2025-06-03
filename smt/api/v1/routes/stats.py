from datetime import datetime

from fastapi import APIRouter, Depends
from fastapi.params import Query

from smt.schemas.stats import ItemStat, ItemStatCreate
from smt.services.dependencies import get_stats_service
from smt.services.stats import StatService


router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/{market_hash_name}", response_model=list[ItemStat])
async def read_stats(
    market_hash_name: str,
    since: datetime = Query(...),
    service: StatService = Depends(get_stats_service),
):
    return await service.list(market_hash_name, since)


@router.post("/add")
async def add_stat(
    stat: ItemStatCreate,
    service: StatService = Depends(get_stats_service),
):
    await service.add_one(stat)


@router.post("/add-multiple")
async def add_stats(
    stats: list[ItemStatCreate],
    service: StatService = Depends(get_stats_service),
):
    await service.add_many(stats)
