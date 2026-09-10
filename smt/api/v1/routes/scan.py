import json
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, status
from steampy.models import GameOptions

from smt.schemas.scan import ScanCandidateDetails, ScanHistoryPoint, ScanRequest, ScanStarted, ScanState
from smt.services.dependencies import get_market_scan_service, get_steam_service
from smt.services.market_scan import MarketScanService, ScanParams
from smt.services.steam import STEAM_COMMUNITY_URL, SteamService
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


@router.get("/{scan_id}/candidate/{market_hash_name:path}", response_model=ScanCandidateDetails)
async def read_candidate(
    scan_id: str,
    market_hash_name: str,
    scan_service: MarketScanService = Depends(get_market_scan_service),
    steam: SteamService = Depends(get_steam_service),
):
    """
    Price history and depth for one candidate, straight from Steam.

    The pool keeps history in the database, but a candidate is not in the pool yet, so
    there is nothing stored to read. The game comes from the scan rather than the caller.
    """
    state = await scan_service.get(scan_id)
    if not state:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Scan {scan_id} is not around any more")

    candidate = next((c for c in state["candidates"] if c["market_hash_name"] == market_hash_name), None)
    if not candidate:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{market_hash_name} is not in scan {scan_id}")

    app_id, context_id = candidate["app_id"], candidate["context_id"]
    days = int(state["params"].get("days") or 30)

    try:
        history = await steam.get_price_history(
            market_hash_name=market_hash_name, game=GameOptions(app_id, context_id), days=days
        )
    except Exception as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"Steam would not send the history: {e}")

    try:
        order_book = await steam.get_order_book(market_hash_name=market_hash_name, app_id=app_id)
    except Exception:
        order_book = None

    return ScanCandidateDetails(
        market_hash_name=market_hash_name,
        listing_url=f"{STEAM_COMMUNITY_URL}/market/listings/{app_id}/{quote(market_hash_name)}",
        history=[
            ScanHistoryPoint(recorded_at=moment.isoformat(), price=price, volume=volume)
            for moment, price, volume in history
        ],
        order_book=_serialisable(order_book),
    )


def _serialisable(book):
    if book is None:
        return None
    return json.loads(json.dumps(book, default=str))


@router.get("/{scan_id}", response_model=ScanState)
async def read_scan(scan_id: str, scan_service: MarketScanService = Depends(get_market_scan_service)):
    state = await scan_service.get(scan_id)
    if not state:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Scan {scan_id} is not around any more")
    return state
