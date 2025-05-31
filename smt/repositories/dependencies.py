from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from smt.db.dependencies import get_db
from smt.repositories.items import ItemRepo


def get_item_repo(
    db: AsyncSession = Depends(get_db),
) -> ItemRepo:
    return ItemRepo(db)
