from fastapi import APIRouter, Depends, Form
from starlette.responses import RedirectResponse

from smt.schemas.pool import PoolItem
from smt.services.dependencies import get_pool_service
from smt.services.pool import PoolService


router = APIRouter(prefix="/pool", tags=["pool"])


@router.get("/", response_model=list[PoolItem])
async def read_pool(service: PoolService = Depends(get_pool_service)):
    return await service.list()


@router.post("/add")
async def add_to_pool(
    asset_id: str = Form(...),
    service: PoolService = Depends(get_pool_service),
):
    await service.add_one(asset_id)
    return RedirectResponse("/pool", status_code=303)


@router.post("/add-multiple")
async def add_multiple_to_pool(
    asset_ids: list[str] = Form(...),
    service: PoolService = Depends(get_pool_service),
):
    await service.add_many(asset_ids)
    return RedirectResponse("/pool", status_code=303)
