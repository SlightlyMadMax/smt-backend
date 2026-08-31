from datetime import UTC, datetime, timedelta
from typing import Optional, Sequence

from smt.db.models import ActionLog
from smt.logger import get_logger
from smt.repositories.action_log import ActionLogRepo
from smt.schemas.action_log import ActionKind, ActionLevel


logger = get_logger("services.action_log")

RETENTION = timedelta(days=30)


class ActionLogService:
    """
    Records what the bot did so the dashboard can show it.

    Only events are recorded, never states: writing down every skipped item on every
    cycle would bury the handful of entries that matter under thousands of repeats.
    """

    def __init__(self, repo: ActionLogRepo):
        self.repo = repo

    async def record(
        self,
        kind: ActionKind,
        message: str,
        level: ActionLevel = ActionLevel.INFO,
        market_hash_name: Optional[str] = None,
        position_id: Optional[int] = None,
    ) -> None:
        try:
            await self.repo.add(
                kind=kind.value,
                message=message,
                level=level.value,
                market_hash_name=market_hash_name,
                position_id=position_id,
            )
        except Exception as e:
            # the journal must never be the reason a trade fails
            logger.error(f"Could not record the {kind.value} action: {e!r}")

    async def list(
        self,
        limit: int = 200,
        level: Optional[str] = None,
        market_hash_name: Optional[str] = None,
    ) -> Sequence[ActionLog]:
        return await self.repo.list(limit=limit, level=level, market_hash_name=market_hash_name)

    async def prune(self) -> int:
        return await self.repo.delete_before(datetime.now(UTC) - RETENTION)
