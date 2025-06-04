from datetime import datetime
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from smt.db.models import PriceHistoryRecord as PriceHistoryRecordORM
from smt.schemas.price_history import PriceHistoryRecordCreate


class PriceHistoryRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_records(self, market_hash_name: str, since: datetime) -> Sequence[PriceHistoryRecordORM]:
        stmt = (
            select(PriceHistoryRecordORM)
            .where(
                PriceHistoryRecordORM.market_hash_name == market_hash_name,
                PriceHistoryRecordORM.recorded_at >= since,
            )
            .order_by(PriceHistoryRecordORM.recorded_at)
        )
        result = await self.session.execute(stmt)

        return result.scalars().all()

    async def add_record(self, price_record: PriceHistoryRecordCreate) -> None:
        self.session.add(PriceHistoryRecordORM(**price_record.model_dump()))
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()

    async def add_records(self, price_records: list[PriceHistoryRecordCreate]) -> None:
        values = [rec.model_dump() for rec in price_records]

        stmt = insert(PriceHistoryRecordORM).values(values)

        # On conflict, do nothing (skip duplicates)
        stmt = stmt.on_conflict_do_nothing(index_elements=["market_hash_name", "recorded_at"])

        try:
            await self.session.execute(stmt)
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
