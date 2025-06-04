from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.params import Query
from starlette import status

from smt.schemas.price_history import (
    PriceHistoryRecord,
    PriceHistoryRecordCreate,
    PriceRecordBulkCreateResponse,
    PriceRecordCreateResponse,
)
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


@router.post(
    "/add",
    response_model=PriceRecordCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_price_record(
    price_record: PriceHistoryRecordCreate,
    service: PriceHistoryService = Depends(get_price_history_service),
):
    created = await service.add_one(price_record)
    if not created:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Record already exists",
        )
    return created


@router.post(
    "/add-multiple",
    response_model=PriceRecordBulkCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_price_records(
    price_records: list[PriceHistoryRecordCreate],
    service: PriceHistoryService = Depends(get_price_history_service),
):
    count = await service.add_many(price_records)
    return PriceRecordBulkCreateResponse(created=count)
