from datetime import datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.exc import NoResultFound

from smt.db.models import PoolItem, Position
from smt.repositories.position import PositionRepo
from smt.schemas.position import PositionCreate, PositionStatus, PositionUpdate


@pytest_asyncio.fixture
def position_repo(db_session) -> PositionRepo:
    return PositionRepo(db_session)


@pytest_asyncio.fixture(autouse=True)
async def setup_test_data(db_session):
    await db_session.execute(delete(Position))
    await db_session.execute(delete(PoolItem))
    await db_session.commit()

    # Create test pool items
    pool_items = [
        PoolItem(
            market_hash_name="ak47_redline",
            name="Pool Item A1",
            app_id="100",
            context_id="1",
            icon_url="https://cdn.com/a1.png",
        ),
        PoolItem(
            market_hash_name="awp_dragon_lore",
            name="Pool Item B2",
            app_id="100",
            context_id="1",
            icon_url="https://cdn.com/b2.png",
        ),
    ]
    db_session.add_all(pool_items)
    await db_session.commit()

    # Create test positions
    positions = [
        Position(
            id=1,
            pool_item_hash="ak47_redline",
            buy_order_id="order_001",
            buy_price=Decimal("25.50"),
            sell_price=Decimal("30.00"),
            quantity=1,
            status=PositionStatus.OPEN,
        ),
        Position(
            id=2,
            pool_item_hash="awp_dragon_lore",
            buy_order_id="order_002",
            buy_price=Decimal("1500.00"),
            sell_price=Decimal("1600.00"),
            quantity=1,
            sell_order_id="sell_002",
            status=PositionStatus.LISTED,
        ),
        Position(
            id=3,
            pool_item_hash="ak47_redline",
            buy_order_id="order_003",
            buy_price=Decimal("26.00"),
            sell_price=Decimal("28.00"),
            quantity=2,
            sell_order_id="sell_003",
            sold_at=datetime.now(timezone.utc),
            status=PositionStatus.CLOSED,
        ),
    ]
    db_session.add_all(positions)
    await db_session.commit()
    yield


@pytest.mark.asyncio
class TestPositionRepo:
    @pytest.mark.parametrize(
        "position_id,expected_item_hash",
        [
            (1, "ak47_redline"),
            (2, "awp_dragon_lore"),
            (3, "ak47_redline"),
        ],
    )
    async def test_get_by_id_success(self, position_repo, position_id, expected_item_hash):
        position = await position_repo.get_by_id(position_id)
        assert position.id == position_id
        assert position.pool_item_hash == expected_item_hash

    async def test_get_by_id_not_found(self, position_repo):
        with pytest.raises(NoResultFound, match="Position with id 999 not found"):
            await position_repo.get_by_id(999)

    @pytest.mark.parametrize(
        "status,expected_ids",
        [
            (PositionStatus.OPEN, [1]),
            (PositionStatus.LISTED, [2]),
            (PositionStatus.CLOSED, [3]),
        ],
    )
    async def test_list_by_status(self, position_repo, status, expected_ids):
        positions = await position_repo.list_by_status(status)
        actual_ids = [pos.id for pos in positions]
        assert set(actual_ids) == set(expected_ids)

    async def test_list_open(self, position_repo):
        positions = await position_repo.list_open()
        assert len(positions) == 1
        assert positions[0].id == 1
        assert positions[0].status == PositionStatus.OPEN

    async def test_list_listed(self, position_repo):
        positions = await position_repo.list_listed()
        assert len(positions) == 1
        assert positions[0].id == 2
        assert positions[0].status == PositionStatus.LISTED

    async def test_list_closed(self, position_repo):
        positions = await position_repo.list_closed()
        assert len(positions) == 1
        assert positions[0].id == 3
        assert positions[0].status == PositionStatus.CLOSED

    async def test_add_position(self, position_repo, db_session):
        position_data = PositionCreate(
            pool_item_hash="ak47_redline",
            buy_order_id="order_new",
            buy_price=30.00,
            sell_price=35.00,
            quantity=3,
        )

        new_position = await position_repo.add(position_data)

        # Verify the returned position
        assert new_position.id is not None
        assert new_position.pool_item_hash == "ak47_redline"
        assert new_position.buy_order_id == "order_new"
        assert new_position.buy_price == Decimal("30.00")
        assert new_position.sell_price == Decimal("35.00")
        assert new_position.quantity == 3
        assert new_position.status == PositionStatus.OPEN
        assert new_position.sell_order_id is None
        assert new_position.sold_at is None

        # Verify it was saved to database
        stmt = select(Position).where(Position.id == new_position.id)
        result = await db_session.execute(stmt)
        saved_position = result.scalar_one()
        assert saved_position.buy_order_id == "order_new"

    async def test_update_position_partial(self, position_repo):
        update_data = PositionUpdate(
            sell_order_id="sell_new",
            status=PositionStatus.LISTED,
        )

        updated_position = await position_repo.update(1, update_data)

        assert updated_position.id == 1
        assert updated_position.sell_order_id == "sell_new"
        assert updated_position.status == PositionStatus.LISTED
        assert updated_position.sold_at is None  # Not updated
        # Original fields should remain
        assert updated_position.buy_order_id == "order_001"
        assert updated_position.buy_price == Decimal("25.50")

    async def test_update_position_full(self, position_repo):
        sold_time = datetime.now(timezone.utc)
        update_data = PositionUpdate(
            sell_order_id="sell_complete",
            status=PositionStatus.CLOSED,
            sold_at=sold_time,
        )

        updated_position = await position_repo.update(1, update_data)

        assert updated_position.id == 1
        assert updated_position.sell_order_id == "sell_complete"
        assert updated_position.status == PositionStatus.CLOSED
        assert abs((updated_position.sold_at.replace(tzinfo=timezone.utc) - sold_time).total_seconds()) < 1

    async def test_update_position_not_found(self, position_repo):
        update_data = PositionUpdate(status=PositionStatus.CLOSED)

        with pytest.raises(NoResultFound):
            await position_repo.update(999, update_data)

    async def test_delete_position(self, position_repo, db_session):
        # Verify position exists before deletion
        position = await position_repo.get_by_id(1)
        assert position is not None

        # Delete the position
        await position_repo.delete(1)

        # Verify it's deleted
        with pytest.raises(NoResultFound):
            await position_repo.get_by_id(1)

        # Verify it's actually removed from database
        stmt = select(Position).where(Position.id == 1)
        result = await db_session.execute(stmt)
        assert result.scalar_one_or_none() is None

    async def test_delete_position_not_found(self, position_repo, db_session):
        # Should not raise an error even if position doesn't exist
        await position_repo.delete(999)

        # Verify other positions still exist
        stmt = select(Position)
        result = await db_session.execute(stmt)
        remaining_positions = result.scalars().all()
        assert len(remaining_positions) == 3  # Original test data still there

    async def test_update_with_none_values(self, position_repo):
        # Test that None values in update don't overwrite existing data
        update_data = PositionUpdate(
            sell_order_id=None,
            status=PositionStatus.LISTED,
            sold_at=None,
        )

        updated_position = await position_repo.update(2, update_data)

        # Status should be updated
        assert updated_position.status == PositionStatus.LISTED
        # None values should set fields to None
        assert updated_position.sell_order_id is None
        assert updated_position.sold_at is None
