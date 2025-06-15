from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy import and_, delete, or_, select
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

    async def add_record(self, price_record: PriceHistoryRecordCreate) -> Optional[PriceHistoryRecordORM]:
        record = PriceHistoryRecordORM(**price_record.model_dump())
        self.session.add(record)
        try:
            await self.session.commit()
            await self.session.refresh(record)
            return record
        except IntegrityError:
            await self.session.rollback()
            return None

    async def add_records(self, price_records: list[PriceHistoryRecordCreate]) -> list[PriceHistoryRecordORM]:
        if not price_records:
            return []

        dumps = [rec.model_dump() for rec in price_records]

        clauses = [
            and_(
                PriceHistoryRecordORM.market_hash_name == d["market_hash_name"],
                PriceHistoryRecordORM.recorded_at == d["recorded_at"],
            )
            for d in dumps
        ]
        existing = []
        if clauses:
            stmt = select(PriceHistoryRecordORM).where(or_(*clauses))
            existing = (await self.session.execute(stmt)).scalars().all()

        existing_keys = {(e.market_hash_name, e.recorded_at) for e in existing}

        new_dicts = [d for d in dumps if (d["market_hash_name"], d["recorded_at"]) not in existing_keys]
        if not new_dicts:
            return []

        new_objs = [PriceHistoryRecordORM(**d) for d in new_dicts]
        self.session.add_all(new_objs)
        await self.session.commit()

        for obj in new_objs:
            await self.session.refresh(obj)

        return new_objs

    async def delete_records_before(self, market_hash_name: str, before_date: datetime) -> int:
        stmt = delete(PriceHistoryRecordORM).where(
            PriceHistoryRecordORM.market_hash_name == market_hash_name, PriceHistoryRecordORM.recorded_at < before_date
        )

        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount
