from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from smt.db.dependencies import get_db
from smt.repositories.items import ItemRepo
from smt.repositories.pool_items import PoolRepo
from smt.repositories.position import PositionRepo
from smt.repositories.price_history import PriceHistoryRepo
from smt.repositories.settings import SettingsRepo


def get_item_repo(db: AsyncSession = Depends(get_db)) -> ItemRepo:
    return ItemRepo(db)


def get_pool_repo(db: AsyncSession = Depends(get_db)) -> PoolRepo:
    return PoolRepo(db)


def get_price_history_repo(db: AsyncSession = Depends(get_db)) -> PriceHistoryRepo:
    return PriceHistoryRepo(db)


def get_settings_repo(db: AsyncSession = Depends(get_db)) -> SettingsRepo:
    return SettingsRepo(db)


def get_position_repo(db: AsyncSession = Depends(get_db)) -> PositionRepo:
    return PositionRepo(db)
