from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from smt.db.dependencies import get_db
from smt.repositories.items import ItemRepo
from smt.repositories.pool_items import PoolRepo
from smt.repositories.stats import StatRepo


def get_item_repo(
    db: AsyncSession = Depends(get_db),
) -> ItemRepo:
    return ItemRepo(db)


def get_pool_repo(
    db: AsyncSession = Depends(get_db),
) -> PoolRepo:
    return PoolRepo(db)


def get_stat_repo(
    db: AsyncSession = Depends(get_db),
) -> StatRepo:
    return StatRepo(db)
