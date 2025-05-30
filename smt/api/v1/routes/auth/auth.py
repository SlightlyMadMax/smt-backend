from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException
from starlette.requests import Request
from starlette.responses import RedirectResponse

from smt.core.config import settings


router = APIRouter()


@router.get("/steam/login")
async def steam_login():
    """Redirects the user to Steam OpenID login."""
    params = {
        "openid.ns": "http://specs.openid.net/auth/2.0",
        "openid.mode": "checkid_setup",
        "openid.return_to": settings.STEAM_RETURN_URL,
        "openid.realm": settings.BASE_URL,
        "openid.claimed_id": "http://specs.openid.net/auth/2.0/identifier_select",
        "openid.identity": "http://specs.openid.net/auth/2.0/identifier_select",
    }
    auth_url = f"{settings.STEAM_OPENID_URL}?{urlencode(params)}"
    return RedirectResponse(auth_url)


@router.get("/steam/callback")
async def steam_callback(request: Request):
    """Handles Steam OpenID login callback."""
    params = dict(request.query_params)

    # Validate required OpenID parameters
    required_keys = {
        "openid.mode",
        "openid.claimed_id",
        "openid.identity",
        "openid.sig",
        "openid.signed",
    }
    if not required_keys.issubset(params.keys()):
        raise HTTPException(
            status_code=400, detail="Missing required OpenID parameters"
        )

    # Validate `openid.return_to` to prevent open redirect attacks
    return_to = params.get("openid.return_to", "")
    if not return_to.startswith(str(settings.STEAM_RETURN_URL)):
        raise HTTPException(status_code=400, detail="Invalid return URL")

    # Validate `state` (CSRF protection)
    session_state = request.session.get("openid_state")
    if params.get("state") != session_state:
        raise HTTPException(
            status_code=400, detail="Invalid state parameter (possible CSRF attack)"
        )

    # Verify OpenID response with Steam
    params["openid.mode"] = "check_authentication"

    async with httpx.AsyncClient() as client:
        response = await client.post(str(settings.STEAM_OPENID_URL), data=params)

    if "is_valid:true" in response.text:
        # Extract Steam ID securely
        openid_claimed_id = params.get("openid.claimed_id")
        steam_id = openid_claimed_id.split("id/")[-1] if openid_claimed_id else None
        if not steam_id:
            raise HTTPException(status_code=400, detail="Invalid Steam ID")

        return {"status": "success", "steam_id": steam_id}

    raise HTTPException(status_code=400, detail="Steam OpenID verification failed")
