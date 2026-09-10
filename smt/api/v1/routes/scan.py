from fastapi import APIRouter, Depends, HTTPException, status

from smt.schemas.scan import ScanRequest, ScanStarted, ScanState
from smt.services.dependencies import get_market_scan_service
from smt.services.market_scan import MarketScanService, ScanParams
from smt.worker.arq import ARQService, get_arq_service


router = APIRouter(prefix="/scan", tags=["scan"])


@router.post("/", response_model=ScanStarted)
async def start_scan(
    payload: ScanRequest,
    scan_service: MarketScanService = Depends(get_market_scan_service),
    arq_service: ARQService = Depends(get_arq_service),
):
    running = await scan_service.latest()
    if running and running["status"] == "running":
        raise HTTPException(status.HTTP_409_CONFLICT, "A scan is already running")

    scan_id = scan_service.new_id()
    params = ScanParams.from_dict(payload.model_dump())
    await arq_service.enqueue("market_scan_task", scan_id, params.as_dict())
    return ScanStarted(scan_id=scan_id)


@router.get("/latest", response_model=ScanState)
async def read_latest_scan(scan_service: MarketScanService = Depends(get_market_scan_service)):
    state = await scan_service.latest()
    if not state:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No scan has been run yet")
    return state


@router.get("/{scan_id}", response_model=ScanState)
async def read_scan(scan_id: str, scan_service: MarketScanService = Depends(get_market_scan_service)):
    state = await scan_service.get(scan_id)
    if not state:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Scan {scan_id} is not around any more")
    return state
