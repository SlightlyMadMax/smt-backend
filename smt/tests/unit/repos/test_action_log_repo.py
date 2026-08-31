from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete

from smt.db.models import ActionLog
from smt.repositories.action_log import ActionLogRepo
from smt.schemas.action_log import ActionKind, ActionLevel
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
