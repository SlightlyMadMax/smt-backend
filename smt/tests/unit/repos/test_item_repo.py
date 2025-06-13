import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.exc import NoResultFound

from smt.db.models import Item
from smt.repositories.items import ItemRepo


@pytest_asyncio.fixture
def item_repo(db_session) -> ItemRepo:
    return ItemRepo(db_session)


@pytest_asyncio.fixture(autouse=True)
async def setup_items(db_session):
    await db_session.execute(delete(Item))
    await db_session.commit()

    items = [
        Item(
            id="a1",
            market_hash_name="a1",
            name="Item A1",
            app_id="100",
            context_id="1",
            icon_url="https://cdn.com/a1.png",
            marketable=True,
        ),
        Item(
            id="b2",
            market_hash_name="b2",
            name="Item B2",
            app_id="100",
            context_id="1",
            icon_url="https://cdn.com/b2.png",
            marketable=False,
        ),
        Item(
            id="c3",
            market_hash_name="c3",
            name="Item C3",
            app_id="200",
            context_id="2",
            icon_url="https://cdn.com/c3.png",
            marketable=True,
        ),
    ]
    db_session.add_all(items)
    await db_session.commit()
    yield


@pytest.mark.asyncio
class TestItemRepo:
    @pytest.mark.parametrize(
        "item_id,expected",
        [
            ("a1", "Item A1"),
            ("b2", "Item B2"),
        ],
    )
    async def test_get_by_id_success(self, item_repo, item_id, expected):
        item = await item_repo.get_by_id(item_id)
        assert item.name == expected
        assert item.id == item_id

    async def test_get_by_id_not_found(self, item_repo):
        with pytest.raises(NoResultFound):
            await item_repo.get_by_id("nonexistent")

    @pytest.mark.parametrize(
        "app_id,context_id,expected_ids",
        [
            ("100", "1", ["a1", "b2"]),
            ("200", "2", ["c3"]),
            ("999", "9", []),
        ],
    )
    async def test_list_for_game(self, item_repo, app_id, context_id, expected_ids):
        results = await item_repo.list_for_game(app_id, context_id)
        ids = [item.id for item in results]
        assert set(ids) == set(expected_ids)

    async def test_replace_for_game_overwrites(self, db_session, item_repo):
        # Replace items for game (100,1) with a new list
        new_items = [
            Item(
                id="d4",
                market_hash_name="d4",
                name="Item D4",
                app_id="100",
                context_id="1",
                icon_url="https://cdn.com/d4.png",
                marketable=True,
            )
        ]
        await item_repo.replace_for_game(app_id="100", context_id="1", items=new_items)
        # After replace, only 'd4' should exist for (100,1)
        remaining = (
            (await db_session.execute(select(Item).where(Item.app_id == "100", Item.context_id == "1"))).scalars().all()
        )
        assert [i.id for i in remaining] == ["d4"]

    async def test_replace_for_game_empty_list(self, db_session, item_repo):
        await item_repo.replace_for_game(app_id="100", context_id="1", items=[])
        remaining = (await db_session.execute(select(Item))).scalars().all()
        ids = [i.id for i in remaining]
        assert set(ids) == {"c3"}
