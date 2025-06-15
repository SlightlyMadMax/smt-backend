import datetime
from datetime import timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from smt.db.models import PriceHistoryRecord
from smt.repositories.price_history import PriceHistoryRepo
from smt.schemas.price_history import PriceHistoryRecordCreate


@pytest_asyncio.fixture
def price_history_repo(db_session) -> PriceHistoryRepo:
    return PriceHistoryRepo(db_session)


@pytest.fixture
def base_time() -> datetime.datetime:
    return datetime.datetime(2025, 6, 13, 12, 0, 0)


@pytest_asyncio.fixture(autouse=True)
async def setup_price_history(db_session, base_time):
    await db_session.execute(delete(PriceHistoryRecord))
    await db_session.commit()

    records = [
        PriceHistoryRecord(
            market_hash_name="item1",
            recorded_at=base_time - timedelta(hours=2),
            price=Decimal(100.0),
            volume=10,
        ),
        PriceHistoryRecord(
            market_hash_name="item1",
            recorded_at=base_time - timedelta(hours=1),
            price=Decimal(110.0),
            volume=15,
        ),
        PriceHistoryRecord(
            market_hash_name="item2",
            recorded_at=base_time - timedelta(hours=1),
            price=Decimal(200.0),
            volume=5,
        ),
    ]
    db_session.add_all(records)
    await db_session.commit()
    yield


@pytest.mark.asyncio
class TestPriceHistoryRepo:
    async def test_list_records_filters_and_orders(self, price_history_repo, base_time):
        since = base_time - timedelta(hours=1, minutes=30)
        results = await price_history_repo.list_records("item1", since)
        # Should return only the record from 1 hour ago, not the 2-hour-old one
        assert len(results) == 1
        assert results[0].price == Decimal(110.0)
        # Ensure ordering by recorded_at
        since2 = base_time - timedelta(hours=3)
        all_records = await price_history_repo.list_records("item1", since2)
        times = [r.recorded_at for r in all_records]
        assert times == sorted(times)

    async def test_add_record_success(self, price_history_repo, db_session):
        new_time = datetime.datetime.now(datetime.UTC)
        payload = PriceHistoryRecordCreate(
            market_hash_name="item3",
            recorded_at=new_time,
            price=Decimal(300.0),
            volume=2,
        )
        created = await price_history_repo.add_record(payload)
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

    async def test_add_record_duplicate(self, price_history_repo, db_session):
        # Use market_hash_name and recorded_at matching an existing record
        existing = (await db_session.execute(select(PriceHistoryRecord).limit(1))).scalar_one()
        payload = PriceHistoryRecordCreate(
            market_hash_name=existing.market_hash_name,
            recorded_at=existing.recorded_at,
            price=Decimal(999.0),
            volume=2,
        )
        result = await price_history_repo.add_record(payload)
        assert result is None

    async def test_add_records_bulk(self, price_history_repo, db_session, base_time):
        batch = [
            PriceHistoryRecordCreate(
                market_hash_name="item1",
                recorded_at=base_time - timedelta(minutes=30),  # new
                price=Decimal(115.0),
                volume=10,
            ),
            PriceHistoryRecordCreate(
                market_hash_name="item2",
                recorded_at=base_time - timedelta(hours=1),  # duplicate existing
                price=Decimal(210.0),
                volume=20,
            ),
            PriceHistoryRecordCreate(
                market_hash_name="item4",
                recorded_at=base_time,
                price=Decimal(400.0),
                volume=30,
            ),
        ]
        created = await price_history_repo.add_records(batch)
        # Should only include the two new unique records
        names_times = {(r.market_hash_name, r.recorded_at) for r in created}
        expected = {
            ("item1", base_time - timedelta(minutes=30)),
            ("item4", base_time),
        }
        assert names_times == expected
        # verify in DB total count: seeded 3 + 2 new = 5
        total = await db_session.execute(select(PriceHistoryRecord))
        assert len(total.scalars().all()) == 5

    async def test_add_records_empty(self, price_history_repo):
        created = await price_history_repo.add_records([])
        assert created == []

    async def test_delete_records_before_success(self, price_history_repo, db_session, base_time):
        # Delete item1 records older than 1.5 hours ago
        cutoff_time = base_time - timedelta(hours=1, minutes=30)
        deleted_count = await price_history_repo.delete_records_before("item1", cutoff_time)

        # Should delete the 2-hour-old record but keep the 1-hour-old record
        assert deleted_count == 1

        # Verify the remaining records
        remaining = await price_history_repo.list_records("item1", base_time - timedelta(hours=3))
        assert len(remaining) == 1
        assert remaining[0].price == Decimal(110.0)  # Only the 1-hour-old record remains

        # Verify item2 records are unaffected
        item2_records = await price_history_repo.list_records("item2", base_time - timedelta(hours=3))
        assert len(item2_records) == 1
        assert item2_records[0].price == Decimal(200.0)

    async def test_delete_records_before_no_matches(self, price_history_repo, base_time):
        # Try to delete records older than 3 hours ago (no records exist that old)
        cutoff_time = base_time - timedelta(hours=3)
        deleted_count = await price_history_repo.delete_records_before("item1", cutoff_time)

        assert deleted_count == 0

        # Also test with non-existent market_hash_name
        deleted_count = await price_history_repo.delete_records_before("nonexistent_item", base_time)
        assert deleted_count == 0
