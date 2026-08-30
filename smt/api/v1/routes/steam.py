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
_cached: Optional[tuple[float, Decimal]] = None


@router.get("/wallet", response_model=WalletBalance)
async def read_wallet(steam: SteamService = Depends(get_steam_service)):
    global _cached

    if _cached and time.monotonic() - _cached[0] < BALANCE_TTL_SECONDS:
        return WalletBalance(balance=_cached[1], cached=True)

    try:
        balance = await steam.get_wallet_balance()
    except Exception as e:
        logger.warning(f"Could not read the wallet balance: {e!r}")
        if _cached:
            return WalletBalance(balance=_cached[1], cached=True, stale=True)
        return WalletBalance(balance=None, cached=False, stale=True)

    _cached = (time.monotonic(), balance)
    return WalletBalance(balance=balance, cached=False)
