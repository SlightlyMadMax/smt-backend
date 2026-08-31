from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from smt.db.models import PoolItem
from smt.db.models import PriceHistoryRecord as PriceHistoryRecordORM
from smt.exceptions import UnknownPoolItem
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

    async def _known_pool_items(self, names: set[str]) -> set[str]:
        if not names:
            return set()
        stmt = select(PoolItem.market_hash_name).where(PoolItem.market_hash_name.in_(names))
        result = await self.session.execute(stmt)
        return {name for name, in result.all()}

    async def add_record(self, price_record: PriceHistoryRecordCreate) -> Optional[PriceHistoryRecordORM]:
        if not await self._known_pool_items({price_record.market_hash_name}):
            raise UnknownPoolItem(f"{price_record.market_hash_name} is not in the pool")

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

        known = await self._known_pool_items({d["market_hash_name"] for d in dumps})
        unknown = {d["market_hash_name"] for d in dumps} - known
        if unknown:
            raise UnknownPoolItem(f"not in the pool: {', '.join(sorted(unknown))}")

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
