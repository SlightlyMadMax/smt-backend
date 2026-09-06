from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete

from smt.db.models import PoolItem, Position
from smt.repositories.position import PositionRepo
from smt.schemas.position import PositionCreate, PositionSortKey, PositionStatus, PositionUpdate, SortOrder
from smt.services.position import PositionService
from smt.utils.steam import FeeSchedule, get_fee_schedule, set_fee_schedule


ITEM_HASH = "AK-47 | Redline (Field-Tested)"


@pytest_asyncio.fixture
def position_repo(db_session) -> PositionRepo:
    return PositionRepo(db_session)


@pytest_asyncio.fixture(autouse=True)
def pinned_fee_schedule():
    """The proceeds below assume Steam's current 86 kopeck minimum fee."""
    original = get_fee_schedule()
    set_fee_schedule(FeeSchedule(minimum=86))
    yield
    set_fee_schedule(original)


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

        assert closed.net_proceeds == Decimal("12.85")
        assert closed.realized_profit == Decimal("2.85")

    async def test_proceeds_are_below_what_the_buyer_paid(self, position_service, position):
        await bring_to_listed(position_service, position)

        closed = await position_service.close(position.id)

        assert closed.net_proceeds < closed.sell_price
        assert closed.net_proceeds + Decimal("2.15") == closed.sell_price

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

        assert total == Decimal("2.85")

    async def test_realized_profit_respects_the_window(self, position_service, position):
        await bring_to_listed(position_service, position)
        await position_service.close(position.id)

        future = datetime.now(timezone.utc) + timedelta(days=1)

        assert await position_service.realized_profit_since(future) == Decimal("0")

    async def test_no_closed_positions_means_zero(self, position_service):
        total = await position_service.realized_profit_since(datetime(2000, 1, 1, tzinfo=timezone.utc))

        assert total == Decimal("0")


@pytest_asyncio.fixture
async def many_positions(position_repo, db_session):
    for n in range(5):
        pos = await position_repo.add(
            PositionCreate(
                pool_item_hash=ITEM_HASH,
                buy_order_id=f"BUY-{n}",
                buy_price=Decimal(10 + n),
                sell_price=Decimal(20),
            )
        )
        if n < 3:
            await position_repo.update(
                pos.id,
                PositionUpdate(status=PositionStatus.CLOSED.value, realized_profit=Decimal(n)),
            )
    yield


@pytest.mark.asyncio
class TestPositionPaging:
    async def test_a_page_is_capped_by_the_limit(self, position_repo, many_positions):
        assert len(await position_repo.list_page(limit=2, offset=0)) == 2

    async def test_the_offset_moves_past_earlier_rows(self, position_repo, many_positions):
        first = await position_repo.list_page(limit=2, offset=0, sort=PositionSortKey.BUY_PRICE, order=SortOrder.ASC)
        second = await position_repo.list_page(limit=2, offset=2, sort=PositionSortKey.BUY_PRICE, order=SortOrder.ASC)

        assert [p.buy_price for p in first] == [Decimal("10.00"), Decimal("11.00")]
        assert [p.buy_price for p in second] == [Decimal("12.00"), Decimal("13.00")]

    async def test_sorting_runs_over_everything_not_just_one_page(self, position_repo, many_positions):
        """The whole point of sorting on the server: page one holds the real maximum."""
        page = await position_repo.list_page(limit=2, offset=0, sort=PositionSortKey.BUY_PRICE, order=SortOrder.DESC)

        assert page[0].buy_price == Decimal("14.00")

    async def test_missing_values_sort_last_in_both_directions(self, position_repo, many_positions):
        ascending = await position_repo.list_page(
            limit=5, offset=0, sort=PositionSortKey.REALIZED_PROFIT, order=SortOrder.ASC
        )
        descending = await position_repo.list_page(
            limit=5, offset=0, sort=PositionSortKey.REALIZED_PROFIT, order=SortOrder.DESC
        )

        assert [p.realized_profit for p in ascending][-2:] == [None, None]
        assert [p.realized_profit for p in descending][-2:] == [None, None]

    async def test_a_status_filter_narrows_the_page_and_the_count(self, position_repo, many_positions):
        page = await position_repo.list_page(limit=10, offset=0, status=PositionStatus.CLOSED)

        assert len(page) == 3
        assert await position_repo.count(PositionStatus.CLOSED) == 3
        assert await position_repo.count() == 5
