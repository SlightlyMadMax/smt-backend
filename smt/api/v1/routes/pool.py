from fastapi import APIRouter, Depends

from smt.schemas.pool import (
    PoolItem,
    PoolItemBulkCreateRequest,
    PoolItemBulkCreateResponse,
    PoolItemCreateRequest,
    PoolItemCreateResponse,
    PoolItemUpdate,
    PoolItemUpdateResponse,
)
from smt.services.dependencies import get_pool_service
from smt.services.pool import PoolService


router = APIRouter(prefix="/pool", tags=["pool"])


@router.get("/", response_model=list[PoolItem])
async def read_pool(service: PoolService = Depends(get_pool_service)):
    return await service.list()


@router.post("/add", response_model=PoolItemCreateResponse)
async def add_to_pool(
    payload: PoolItemCreateRequest,
    service: PoolService = Depends(get_pool_service),
):
    created = await service.add_one(payload.asset_id)
    return PoolItemCreateResponse(created=created)


@router.post("/add-multiple", response_model=PoolItemBulkCreateResponse)
async def add_multiple_to_pool(
    payload: PoolItemBulkCreateRequest,
    service: PoolService = Depends(get_pool_service),
):
    count = await service.add_many(payload.asset_ids)
    return PoolItemBulkCreateResponse(count=count)


@router.patch("/{market_hash_name}", response_model=PoolItemUpdateResponse)
async def update(
    market_hash_name: str,
    payload: PoolItemUpdate,
    service: PoolService = Depends(get_pool_service),
):
    updated = await service.update(market_hash_name, payload)
    return PoolItemUpdateResponse(updated=updated)
