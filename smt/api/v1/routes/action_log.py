from datetime import timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, Query

from smt.schemas.action_log import ActionLevel, ActionLogEntry, ActionLogPurged
from smt.services.action_log import ActionLogService
from smt.services.dependencies import get_action_log_service


router = APIRouter(prefix="/actions", tags=["actions"])


@router.get("/", response_model=List[ActionLogEntry])
async def read_actions(
    limit: int = Query(200, ge=1, le=1000),
    level: Optional[ActionLevel] = Query(None),
    market_hash_name: Optional[str] = Query(None),
    service: ActionLogService = Depends(get_action_log_service),
):
    entries = await service.list(
        limit=limit,
        level=level.value if level else None,
        market_hash_name=market_hash_name,
    )
    return [ActionLogEntry.model_validate(entry) for entry in entries]


@router.delete("/", response_model=ActionLogPurged)
async def purge_actions(
    older_than_days: int = Query(0, ge=0, le=3650),
    service: ActionLogService = Depends(get_action_log_service),
):
    removed = await service.purge(timedelta(days=older_than_days))
    return ActionLogPurged(removed=removed)
