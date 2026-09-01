from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query

from smt.schemas.action_log import (
    ActionLevel,
    ActionLogEntry,
    ActionLogPage,
    ActionLogPurged,
    ActionLogSortKey,
)
from smt.schemas.position import SortOrder
from smt.services.action_log import ActionLogService
from smt.services.dependencies import get_action_log_service


router = APIRouter(prefix="/actions", tags=["actions"])


@router.get("/", response_model=ActionLogPage)
async def read_actions(
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    level: Optional[ActionLevel] = Query(None),
    market_hash_name: Optional[str] = Query(None),
    sort: ActionLogSortKey = Query(ActionLogSortKey.OCCURRED_AT),
    order: SortOrder = Query(SortOrder.DESC),
    service: ActionLogService = Depends(get_action_log_service),
):
    level_value = level.value if level else None
    entries = await service.list_page(
        limit=limit,
        offset=offset,
        level=level_value,
        market_hash_name=market_hash_name,
        sort=sort,
        order=order,
    )
    return ActionLogPage(
        items=[ActionLogEntry.model_validate(entry) for entry in entries],
        total=await service.count(level=level_value, market_hash_name=market_hash_name),
    )


@router.delete("/", response_model=ActionLogPurged)
async def purge_actions(
    older_than_days: int = Query(0, ge=0, le=3650),
    service: ActionLogService = Depends(get_action_log_service),
):
    removed = await service.purge(timedelta(days=older_than_days))
    return ActionLogPurged(removed=removed)
