from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete

from smt.db.models import PoolItem, Position
from smt.repositories.position import PositionRepo
from smt.schemas.position import PositionCreate, PositionStatus, PositionUpdate


ITEM_HASH = "AK-47 | Redline (Field-Tested)"


@pytest_asyncio.fixture
def position_repo(db_session) -> PositionRepo:
    return PositionRepo(db_session)


@pytest_asyncio.fixture(autouse=True)
async def setup_positions(db_session):
    await db_session.execute(delete(Position))
    await db_session.execute(delete(PoolItem))
    db_session.add(
        PoolItem(
            market_hash_name=ITEM_HASH,
            name="AK-47 | Redline",
            app_id="730",
            context_id="2",
            icon_url="http://example.com/icon.png",
        )
    )
    await db_session.commit()
    yield


@pytest_asyncio.fixture
async def position(position_repo) -> Position:
    return await position_repo.add(
        PositionCreate(
            pool_item_hash=ITEM_HASH,
            buy_order_id="BUY-1",
            buy_price=Decimal("10.00"),
            sell_price=Decimal("15.00"),
        )
    )


@pytest.mark.asyncio
class TestPositionRepoUpdate:
    async def test_update_applies_only_provided_fields(self, position_repo, position):
        """A partial update must not reset the fields the caller left out."""
        await position_repo.update(
            position.id,
            PositionUpdate(asset_id="ASSET-1", status=PositionStatus.BOUGHT),
        )

        updated = await position_repo.update(
            position.id,
            PositionUpdate(sell_order_id="SELL-1", status=PositionStatus.LISTED),
        )

        assert updated.status == PositionStatus.LISTED
        assert updated.sell_order_id == "SELL-1"
        assert updated.asset_id == "ASSET-1"

    async def test_full_lifecycle_preserves_history(self, position_repo, position):
        """OPEN -> BOUGHT -> LISTED -> CLOSED must accumulate data, not overwrite it."""
        await position_repo.update(
            position.id,
            PositionUpdate(asset_id="ASSET-1", status=PositionStatus.BOUGHT),
        )
        bought = await position_repo.get_by_id(position.id)
        assert bought.asset_id == "ASSET-1"

        await position_repo.update(
            position.id,
            PositionUpdate(sell_order_id="SELL-1", status=PositionStatus.LISTED),
        )

        closed = await position_repo.update(position.id, PositionUpdate(status=PositionStatus.CLOSED))

        assert closed.status == PositionStatus.CLOSED
        assert closed.asset_id == "ASSET-1"
        assert closed.sell_order_id == "SELL-1"
        assert closed.buy_order_id == "BUY-1"
        assert closed.buy_price == Decimal("10.00")

    async def test_update_can_explicitly_clear_a_field(self, position_repo, position):
        """Passing None explicitly is still a real update, unlike omitting the field."""
        await position_repo.update(position.id, PositionUpdate(asset_id="ASSET-1"))

        cleared = await position_repo.update(position.id, PositionUpdate(asset_id=None))

        assert cleared.asset_id is None

    async def test_empty_update_is_a_noop(self, position_repo, position):
        unchanged = await position_repo.update(position.id, PositionUpdate())

        assert unchanged.status == PositionStatus.OPEN
        assert unchanged.buy_order_id == "BUY-1"
