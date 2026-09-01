from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete

from smt.db.models import ActionLog
from smt.repositories.action_log import ActionLogRepo
from smt.schemas.action_log import ActionKind, ActionLevel, ActionLogSortKey
from smt.schemas.position import SortOrder
from smt.services.action_log import ActionLogService


@pytest_asyncio.fixture
def action_log_repo(db_session) -> ActionLogRepo:
    return ActionLogRepo(db_session)


@pytest_asyncio.fixture
def action_log_service(action_log_repo) -> ActionLogService:
    return ActionLogService(action_log_repo)


@pytest_asyncio.fixture(autouse=True)
async def clean_log(db_session):
    await db_session.execute(delete(ActionLog))
    await db_session.commit()
    yield


@pytest.mark.asyncio
class TestActionLogRepo:
    async def test_records_an_entry(self, action_log_repo):
        entry = await action_log_repo.add(kind="position_closed", message="Sold at 6.03")

        assert entry.id is not None
        assert entry.level == "info"
        assert entry.occurred_at is not None

    async def test_newest_entries_come_first(self, action_log_repo):
        await action_log_repo.add(kind="a", message="first")
        await action_log_repo.add(kind="b", message="second")

        entries = await action_log_repo.list()

        assert [e.message for e in entries] == ["second", "first"]

    async def test_filters_by_level(self, action_log_repo):
        await action_log_repo.add(kind="a", message="quiet", level="info")
        await action_log_repo.add(kind="b", message="loud", level="error")

        entries = await action_log_repo.list(level="error")

        assert [e.message for e in entries] == ["loud"]

    async def test_filters_by_item(self, action_log_repo):
        await action_log_repo.add(kind="a", message="one", market_hash_name="Item A")
        await action_log_repo.add(kind="b", message="two", market_hash_name="Item B")

        entries = await action_log_repo.list(market_hash_name="Item A")

        assert [e.message for e in entries] == ["one"]

    async def test_respects_the_limit(self, action_log_repo):
        for i in range(5):
            await action_log_repo.add(kind="a", message=f"entry {i}")

        assert len(await action_log_repo.list(limit=2)) == 2

    async def test_a_long_message_is_truncated_to_fit(self, action_log_repo):
        entry = await action_log_repo.add(kind="a", message="x" * 900)

        assert len(entry.message) == 512

    async def test_delete_before_removes_only_old_entries(self, action_log_repo, db_session):
        old = ActionLog(
            kind="a",
            message="ancient",
            level="info",
            occurred_at=datetime.now(timezone.utc) - timedelta(days=90),
        )
        db_session.add(old)
        await db_session.commit()
        await action_log_repo.add(kind="b", message="recent")

        removed = await action_log_repo.delete_before(datetime.now(timezone.utc) - timedelta(days=30))

        assert removed == 1
        assert [e.message for e in await action_log_repo.list()] == ["recent"]


@pytest.mark.asyncio
class TestActionLogService:
    async def test_records_through_the_service(self, action_log_service, action_log_repo):
        await action_log_service.record(
            ActionKind.POSITION_BOUGHT,
            "Bought at 3.45",
            level=ActionLevel.INFO,
            market_hash_name="Item A",
            position_id=7,
        )

        entries = await action_log_repo.list()

        assert entries[0].kind == "position_bought"
        assert entries[0].position_id == 7

    async def test_a_failing_journal_never_breaks_the_caller(self, action_log_service):
        async def boom(**kwargs):
            raise RuntimeError("database is gone")

        action_log_service.repo.add = boom

        await action_log_service.record(ActionKind.CYCLE_FAILED, "anything")

    async def test_purge_removes_everything(self, action_log_service, action_log_repo):
        await action_log_repo.add(kind="a", message="one")
        await action_log_repo.add(kind="b", message="two")

        removed = await action_log_service.purge()

        assert removed == 2
        assert await action_log_repo.list() == []

    async def test_purge_keeps_entries_inside_the_window(self, action_log_service, action_log_repo):
        await action_log_repo.add(kind="a", message="recent")

        assert await action_log_service.purge(timedelta(days=1)) == 0

    async def test_prune_removes_only_what_aged_out(self, action_log_service, action_log_repo, db_session):
        db_session.add(
            ActionLog(
                kind="a",
                message="ancient",
                level="info",
                occurred_at=datetime.now(timezone.utc) - timedelta(days=40),
            )
        )
        await db_session.commit()
        await action_log_repo.add(kind="b", message="recent")

        removed = await action_log_service.prune()

        assert removed == 1
        assert [e.message for e in await action_log_repo.list()] == ["recent"]


@pytest.mark.asyncio
class TestActionLogPaging:
    async def test_a_page_is_capped_and_the_total_is_not(self, action_log_repo):
        for i in range(5):
            await action_log_repo.add(kind="a", message=f"entry {i}")

        assert len(await action_log_repo.list_page(limit=2, offset=0)) == 2
        assert await action_log_repo.count() == 5

    async def test_the_offset_moves_past_earlier_rows(self, action_log_repo):
        for i in range(4):
            await action_log_repo.add(kind="a", message=f"entry {i}")

        second = await action_log_repo.list_page(limit=2, offset=2, sort=ActionLogSortKey.KIND)

        assert len(second) == 2

    async def test_a_filter_narrows_the_page_and_the_total(self, action_log_repo):
        await action_log_repo.add(kind="a", message="quiet", level="info")
        await action_log_repo.add(kind="b", message="loud", level="error")

        page = await action_log_repo.list_page(limit=10, offset=0, level="error")

        assert [e.message for e in page] == ["loud"]
        assert await action_log_repo.count(level="error") == 1
        assert await action_log_repo.count() == 2

    async def test_sorting_by_kind_runs_over_everything(self, action_log_repo):
        await action_log_repo.add(kind="zeta", message="last")
        await action_log_repo.add(kind="alpha", message="first")

        page = await action_log_repo.list_page(limit=1, offset=0, sort=ActionLogSortKey.KIND, order=SortOrder.ASC)

        assert page[0].kind == "alpha"
