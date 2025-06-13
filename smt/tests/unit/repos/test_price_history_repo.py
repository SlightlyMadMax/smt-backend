import datetime
from datetime import timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from smt.db.models import PriceHistoryRecord
from smt.repositories.price_history import PriceHistoryRepo
from smt.schemas.price_history import PriceHistoryRecordCreate


@pytest_asyncio.fixture(autouse=True)
async def setup_price_history(db_session):
    await db_session.execute(delete(PriceHistoryRecord))
    await db_session.commit()

    base_time = datetime.datetime.now(datetime.UTC)
    records = [
        PriceHistoryRecord(
            market_hash_name="item1",
            recorded_at=base_time - timedelta(hours=2),
            price=Decimal(100.0),
        ),
        PriceHistoryRecord(
            market_hash_name="item1",
            recorded_at=base_time - timedelta(hours=1),
            price=Decimal(110.0),
        ),
        PriceHistoryRecord(
            market_hash_name="item2",
            recorded_at=base_time - timedelta(hours=1),
            price=Decimal(200.0),
        ),
    ]
    db_session.add_all(records)
    await db_session.commit()
    yield


@pytest.mark.asyncio
class TestPriceHistoryRepo:
    async def test_list_records_filters_and_orders(self, db_session):
        repo = PriceHistoryRepo(db_session)
        since = datetime.datetime.now(datetime.UTC) - timedelta(hours=1, minutes=30)
        results = await repo.list_records("item1", since)
        # Should return only the record from 1 hour ago, not the 2-hour-old one
        assert len(results) == 1
        assert results[0].price == 110.0
        # Ensure ordering by recorded_at
        since2 = datetime.datetime.now(datetime.UTC) - timedelta(hours=3)
        all_records = await repo.list_records("item1", since2)
        times = [r.recorded_at for r in all_records]
        assert times == sorted(times)

    async def test_add_record_success(self, db_session):
        repo = PriceHistoryRepo(db_session)
        new_time = datetime.datetime.now(datetime.UTC)
        payload = PriceHistoryRecordCreate(
            market_hash_name="item3",
            recorded_at=new_time,
            price=300.0,
        )
        created = await repo.add_record(payload)
        assert created is not None
        assert created.market_hash_name == payload.market_hash_name
        assert created.price == payload.price
        # verify in DB
        stmt = select(PriceHistoryRecord).where(
            PriceHistoryRecord.market_hash_name == "item3",
            PriceHistoryRecord.recorded_at == new_time,
        )
        row = (await db_session.execute(stmt)).scalar_one()
        assert row.price == 300.0

    async def test_add_record_duplicate(self, db_session):
        repo = PriceHistoryRepo(db_session)
        # Use market_hash_name and recorded_at matching an existing record
        existing = (await db_session.execute(select(PriceHistoryRecord).limit(1))).scalar_one()
        payload = PriceHistoryRecordCreate(
            market_hash_name=existing.market_hash_name,
            recorded_at=existing.recorded_at,
            price=999.0,
        )
        result = await repo.add_record(payload)
        assert result is None

    async def test_add_records_bulk(self, db_session):
        repo = PriceHistoryRepo(db_session)
        now = datetime.datetime.now(datetime.UTC)
        batch = [
            PriceHistoryRecordCreate(
                market_hash_name="item1",
                recorded_at=now - timedelta(minutes=30),  # new
                price=115.0,
            ),
            PriceHistoryRecordCreate(
                market_hash_name="item2",
                recorded_at=now - timedelta(hours=1),  # duplicate existing
                price=210.0,
            ),
            PriceHistoryRecordCreate(
                market_hash_name="item4",
                recorded_at=now,
                price=400.0,
            ),
        ]
        created = await repo.add_records(batch)
        # Should only include the two new unique records
        names_times = {(r.market_hash_name, r.recorded_at) for r in created}
        expected = {
            ("item1", now - timedelta(minutes=30)),
            ("item4", now),
        }
        assert names_times == expected
        # verify in DB total count: seeded 3 + 2 new = 5
        total = await db_session.execute(select(PriceHistoryRecord))
        assert len(total.scalars().all()) == 5

    async def test_add_records_empty(self, db_session):
        repo = PriceHistoryRepo(db_session)
        created = await repo.add_records([])
        assert created == []
