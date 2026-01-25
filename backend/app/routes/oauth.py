from fastapi import APIRouter, HTTPException

from ..services.google_auth import get_auth_url, save_token_from_code, load_credentials

router = APIRouter()


@router.get("/oauth/start")
async def oauth_start():
    return {"auth_url": get_auth_url()}


@router.get("/oauth/callback")
async def oauth_callback(code: str | None = None):
    if not code:
        raise HTTPException(status_code=400, detail="missing_code")
    save_token_from_code(code)
    return {"status": "authorized"}


@router.get("/oauth/status")
async def oauth_status():
    creds = load_credentials()
    return {"authorized": bool(creds and creds.valid)}
