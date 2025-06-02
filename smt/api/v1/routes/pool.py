from typing import List

from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy.exc import NoResultFound
from starlette.responses import RedirectResponse

from smt.repositories.dependencies import get_item_repo, get_pool_repo
from smt.repositories.items import ItemRepo
from smt.repositories.pool_items import PoolRepo
from smt.schemes.pool import PoolItem, PoolItemCreate


router = APIRouter(prefix="/pool", tags=["pool"])


@router.get("/", response_model=List[PoolItem])
async def read_pool(
    repo: PoolRepo = Depends(get_pool_repo),
):
    return await repo.list_items()


@router.post("/add")
async def add_to_pool(
    asset_id: str = Form(...),
    item_repo: ItemRepo = Depends(get_item_repo),
    pool_repo: PoolRepo = Depends(get_pool_repo),
):
    try:
        asset = await item_repo.get_by_id(asset_id)
    except NoResultFound:
        raise HTTPException(404, f"Inventory item {asset_id} not found")

    item = PoolItemCreate(
        market_hash_name=asset.market_hash_name,
        display_name=asset.name,
        icon_url=asset.icon_url,
    )

    await pool_repo.add_item(item)
    return RedirectResponse("/pool", status_code=303)


@router.post("/add-multiple")
async def add_multiple_to_pool(
    asset_ids: list[str] = Form(...),
    item_repo: ItemRepo = Depends(get_item_repo),
    pool_repo: PoolRepo = Depends(get_pool_repo),
):
    if not asset_ids:
        raise HTTPException(400, detail="No asset IDs provided")

    create_payloads: list[PoolItemCreate] = []
    for asset_id in asset_ids:
        try:
            asset = await item_repo.get_by_id(asset_id)
            create_payloads.append(
                PoolItemCreate(
                    market_hash_name=asset.market_hash_name,
                    display_name=asset.name,
                    icon_url=asset.icon_url,
                )
            )
        except NoResultFound:
            continue

    await pool_repo.add_items(create_payloads)

    return RedirectResponse("/pool", status_code=303)
