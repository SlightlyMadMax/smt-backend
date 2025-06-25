from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.exc import NoResultFound

from smt.db.models import PoolItem
from smt.repositories.pool_items import PoolRepo
from smt.schemas.pool import PoolItemCreate, PoolItemUpdate


@pytest_asyncio.fixture
def pool_repo(db_session) -> PoolRepo:
    return PoolRepo(db_session)


@pytest_asyncio.fixture(autouse=True)
async def setup_pool_items(db_session):
    await db_session.execute(delete(PoolItem))
    await db_session.commit()

    pool_items = [
        PoolItem(
            market_hash_name="a1",
            name="Pool Item A1",
            app_id="100",
            context_id="1",
            icon_url="https://cdn.com/a1.png",
        ),
        PoolItem(
            market_hash_name="b2",
            name="Pool Item B2",
            app_id="100",
            context_id="1",
            icon_url="https://cdn.com/b2.png",
        ),
        PoolItem(
            market_hash_name="c3",
            name="Pool Item C3",
            app_id="200",
            context_id="2",
            icon_url="https://cdn.com/c3.png",
        ),
    ]

    db_session.add_all(pool_items)
    await db_session.commit()
    yield


@pytest.mark.asyncio
class TestPoolItemsRepo:
    async def test_list(self, pool_repo):
        pool_items = await pool_repo.list_items()
        hash_names = [p.market_hash_name for p in pool_items]
        assert set(hash_names) == {"a1", "b2", "c3"}

    @pytest.mark.parametrize(
        "market_hash_name,expected_name",
        [
            ("a1", "Pool Item A1"),
            ("b2", "Pool Item B2"),
        ],
    )
    async def test_get_by_market_hash_name_success(self, pool_repo, market_hash_name, expected_name):
        pool_item = await pool_repo.get_by_market_hash_name(market_hash_name)
        assert pool_item.market_hash_name == market_hash_name
        assert pool_item.name == expected_name

    async def test_get_by_market_hash_name_not_found(self, pool_repo):
        with pytest.raises(NoResultFound):
            await pool_repo.get_by_market_hash_name("nonexistent")

    @pytest.mark.parametrize(
        "market_hash_names,expected_set",
        [(["a1", "c3"], {"a1", "c3"}), ([], set()), (["nope"], set())],
    )
    async def test_get_many(self, pool_repo, market_hash_names, expected_set):
        pool_items = await pool_repo.get_many(market_hash_names)
        hash_names = {p.market_hash_name for p in pool_items}
        assert hash_names == expected_set

    async def test_add_item_success(self, pool_repo, db_session):
        pool_item = PoolItemCreate(
            market_hash_name="d4",
            name="Pool Item D4",
            app_id="200",
            context_id="2",
            icon_url="https://cdn.com/d4.png",
        )
        created_pool_item = await pool_repo.add_item(pool_item)
        assert created_pool_item is not None
        assert created_pool_item.market_hash_name == pool_item.market_hash_name
        # verify in DB
        stmt = select(PoolItem).where(PoolItem.market_hash_name == "d4")
        row = (await db_session.execute(stmt)).scalar_one()
        assert row.name == "Pool Item D4"

    async def test_add_item_duplicate(self, pool_repo):
        pool_item = PoolItemCreate(
            market_hash_name="c3",
            name="Pool Item C3",
            app_id="200",
            context_id="2",
            icon_url="https://cdn.com/c3.png",
        )
        created_pool_item = await pool_repo.add_item(pool_item)
        assert created_pool_item is None

    @pytest.mark.parametrize(
        "pool_items,expected_set",
        [
            (
                [
                    PoolItemCreate(
                        market_hash_name="d4",
                        name="Pool Item D4",
                        app_id="200",
                        context_id="2",
                        icon_url="https://cdn.com/d4.png",
                    ),
                    PoolItemCreate(
                        market_hash_name="e5",
                        name="Pool Item E5",
                        app_id="200",
                        context_id="2",
                        icon_url="https://cdn.com/e5.png",
                    ),
                ],
                {"Pool Item D4", "Pool Item E5"},
            ),
            (
                [
                    PoolItemCreate(
                        market_hash_name="c3",
                        name="Pool Item C3",
                        app_id="200",
                        context_id="2",
                        icon_url="https://cdn.com/c3.png",
                    ),
                    PoolItemCreate(
                        market_hash_name="e5",
                        name="Pool Item E5",
                        app_id="200",
                        context_id="2",
                        icon_url="https://cdn.com/e5.png",
                    ),
                ],
                {"Pool Item E5"},
            ),
            ([], set()),
        ],
    )
    async def test_add_items(self, pool_repo, pool_items, expected_set):
        created_pool_items = await pool_repo.add_items(pool_items)
        names = [p.name for p in created_pool_items]
        assert set(names) == expected_set

    async def test_update_no_fields(self, db_session):
        repo = PoolRepo(db_session)
        payload = PoolItemUpdate()  # all fields None
        result = await repo.update("a1", payload)
        assert result is None

    async def test_update_nonexistent(self, db_session):
        repo = PoolRepo(db_session)
        payload = PoolItemUpdate(name="New Name")
        result = await repo.update("does_not_exist", payload)
        assert result is None

    async def test_update_success(self, pool_repo):
        payload = PoolItemUpdate(
            current_lowest_price=Decimal(10.0),
            current_median_price=Decimal(12.0),
            current_volume24h=100,
            buy_price=Decimal(9.0),
            sell_price=Decimal(13.0),
            max_listed=10,
        )
        updated_item = await pool_repo.update(market_hash_name="a1", payload=payload)
        assert updated_item is not None
        assert updated_item.market_hash_name == "a1"
        assert updated_item.max_listed == 10

    async def test_remove_success(self, pool_repo, db_session):
        all_items = await pool_repo.list_items()
        hash_names_before = {p.market_hash_name for p in all_items}
        assert "a1" in hash_names_before

        result = await pool_repo.remove("a1")
        assert result is True

        all_items_after = await pool_repo.list_items()
        hash_names_after = {p.market_hash_name for p in all_items_after}
        assert "a1" not in hash_names_after
        assert len(hash_names_after) == len(hash_names_before) - 1

    async def test_remove_nonexistent(self, pool_repo):
        result = await pool_repo.remove("nonexistent")
        assert result is False

    @pytest.mark.parametrize(
        "market_hash_names,expected_removed_count,expected_remaining",
        [
            (["a1", "b2"], 2, {"c3"}),  # Remove two existing items
            (["a1", "nonexistent", "c3"], 2, {"b2"}),  # Mix of existing and non-existing
            (["nonexistent", "also_fake"], 0, {"a1", "b2", "c3"}),  # Remove only non-existing
            ([], 0, {"a1", "b2", "c3"}),  # Empty list
            (["a1", "b2", "c3"], 3, set()),  # Remove all items
        ],
    )
    async def test_remove_many(self, pool_repo, market_hash_names, expected_removed_count, expected_remaining):
        removed_count = await pool_repo.remove_many(market_hash_names)
        assert removed_count == expected_removed_count

        remaining_items = await pool_repo.list_items()
        remaining_hash_names = {p.market_hash_name for p in remaining_items}
        assert remaining_hash_names == expected_remaining

    async def test_remove_many_empty_list(self, pool_repo):
        result = await pool_repo.remove_many([])
        assert result == 0

        all_items = await pool_repo.list_items()
        assert len(all_items) == 3
