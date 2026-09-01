from fastapi import APIRouter, Depends, Query

from smt.schemas.statistics import StatisticsOverview
from smt.services.dependencies import get_statistics_service
from smt.services.statistics import StatisticsService


router = APIRouter(prefix="/statistics", tags=["statistics"])


@router.get("/", response_model=StatisticsOverview)
async def read_statistics(
    top: int = Query(5, ge=1, le=50),
    days: int = Query(30, ge=1, le=365),
    service: StatisticsService = Depends(get_statistics_service),
):
    return StatisticsOverview(**await service.overview(top=top, days=days))
