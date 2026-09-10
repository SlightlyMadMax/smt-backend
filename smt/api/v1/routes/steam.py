import time
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends

from smt.logger import get_logger
from smt.schemas.steam import WalletBalance
from smt.services.dependencies import get_steam_service
from smt.services.steam import SteamService


logger = get_logger("api.steam")
router = APIRouter(prefix="/steam", tags=["steam"])

# The header asks for this on every page load, so the value is held briefly to keep
# navigation from spending the Steam request budget.
BALANCE_TTL_SECONDS = 60
RETRY_AFTER_FAILURE_SECONDS = 60
_cached: Optional[tuple[float, Decimal]] = None
_failed_at: Optional[float] = None


def _stale() -> WalletBalance:
    if _cached:
        return WalletBalance(balance=_cached[1], cached=True, stale=True)
    return WalletBalance(balance=None, cached=False, stale=True)


@router.get("/wallet", response_model=WalletBalance)
async def read_wallet(steam: SteamService = Depends(get_steam_service)):
    """Steam meters the page this comes from, so a failure is remembered as well as a success."""
    global _cached, _failed_at

    now = time.monotonic()
    if _cached and now - _cached[0] < BALANCE_TTL_SECONDS:
        return WalletBalance(balance=_cached[1], cached=True)

    if _failed_at and now - _failed_at < RETRY_AFTER_FAILURE_SECONDS:
        return _stale()

    try:
        balance = await steam.get_wallet_balance()
    except Exception as e:
        _failed_at = now
        logger.warning(f"Could not read the wallet balance, not trying again for a minute: {e!r}")
        return _stale()

    _cached = (now, balance)
    _failed_at = None
    return WalletBalance(balance=balance, cached=False)
