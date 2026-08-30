from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete

from smt.db.models import PoolItem, Position
from smt.repositories.position import PositionRepo
from smt.schemas.position import PositionCreate, PositionStatus, PositionUpdate
from smt.services.position import PositionService


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


@pytest_asyncio.fixture
def position_service(position_repo) -> PositionService:
    return PositionService(position_repo)


async def bring_to_listed(service, position):
    await service.mark_as_bought(position.id, asset_id=f"ASSET-{position.id}")
    await service.mark_as_listing_pending(position.id)
    await service.mark_as_listed(position.id, sell_order_id=f"LISTING-{position.id}")


@pytest.mark.asyncio
class TestRealizedProfit:
    async def test_close_records_proceeds_net_of_fees(self, position_service, position):
        await bring_to_listed(position_service, position)

        closed = await position_service.close(position.id)

        assert closed.net_proceeds == Decimal("13.05")
        assert closed.realized_profit == Decimal("3.05")

    async def test_proceeds_are_below_what_the_buyer_paid(self, position_service, position):
        await bring_to_listed(position_service, position)

        closed = await position_service.close(position.id)

        assert closed.net_proceeds < closed.sell_price
        assert closed.net_proceeds + Decimal("1.95") == closed.sell_price

    async def test_realized_profit_sums_only_closed_positions(self, position_service, position_repo, position):
        await bring_to_listed(position_service, position)
        await position_service.close(position.id)

        other = await position_repo.add(
            PositionCreate(
                pool_item_hash=ITEM_HASH,
                buy_order_id="BUY-2",
                buy_price=Decimal("10.00"),
                sell_price=Decimal("15.00"),
            )
        )
        await bring_to_listed(position_service, other)

        total = await position_service.realized_profit_since(datetime(2000, 1, 1, tzinfo=timezone.utc))

        assert total == Decimal("3.05")

    async def test_realized_profit_respects_the_window(self, position_service, position):
        await bring_to_listed(position_service, position)
        await position_service.close(position.id)

        future = datetime.now(timezone.utc) + timedelta(days=1)

        assert await position_service.realized_profit_since(future) == Decimal("0")

    async def test_no_closed_positions_means_zero(self, position_service):
        total = await position_service.realized_profit_since(datetime(2000, 1, 1, tzinfo=timezone.utc))

        assert total == Decimal("0")
