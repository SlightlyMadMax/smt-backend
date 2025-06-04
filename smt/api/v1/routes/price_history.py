from datetime import datetime

from fastapi import APIRouter, Depends
from fastapi.params import Query

from smt.schemas.price_history import PriceHistoryRecord, PriceHistoryRecordCreate
from smt.services.dependencies import get_price_history_service
from smt.services.price_history import PriceHistoryService


router = APIRouter(prefix="/price_records", tags=["price_records"])


@router.get("/{market_hash_name}", response_model=list[PriceHistoryRecord])
async def read_price_records(
    market_hash_name: str,
    since: datetime = Query(...),
    service: PriceHistoryService = Depends(get_price_history_service),
):
    return await service.list(market_hash_name, since)


@router.post("/add")
async def add_price_record(
    price_record: PriceHistoryRecordCreate,
    service: PriceHistoryService = Depends(get_price_history_service),
):
    await service.add_one(price_record)


@router.post("/add-multiple")
async def add_price_records(
    price_records: list[PriceHistoryRecordCreate],
    service: PriceHistoryService = Depends(get_price_history_service),
):
    await service.add_many(price_records)
