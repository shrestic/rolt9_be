import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, Cookie, Depends, HTTPException
from fastapi.responses import RedirectResponse, Response

from app.core.config import settings
from app.core.crypto import encrypt_str
from app.core.security import create_session_token
from app.dependencies.services import get_oauth_service, get_user_repository
from app.repositories.user import UserRepository
from app.services.discord_oauth import DiscordOAuthService

router = APIRouter()

DISCORD_AUTHORIZE = "https://discord.com/api/oauth2/authorize"
SESSION_COOKIE = "rolt9_session"
STATE_COOKIE = "oauth_state"


@router.get("/discord/login")
async def discord_login():
    state = secrets.token_urlsafe(24)
    params = {
        "client_id": settings.DISCORD_CLIENT_ID,
        "response_type": "code",
        "scope": "identify guilds",
        "redirect_uri": settings.DISCORD_REDIRECT_URI,
        "state": state,
        "prompt": "consent",
    }
    resp = RedirectResponse(url=f"{DISCORD_AUTHORIZE}?{urlencode(params)}", status_code=307)
    resp.set_cookie(
        STATE_COOKIE,
        state,
        max_age=600,
        httponly=True,
        secure=False,
        samesite="lax",
        path="/",
    )
    return resp


@router.get("/discord/callback")
async def discord_callback(
    code: str,
    state: str,
    oauth_state: str | None = Cookie(default=None),
    oauth: DiscordOAuthService = Depends(get_oauth_service),
    users: UserRepository = Depends(get_user_repository),
):
    if not oauth_state or oauth_state != state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    tokens = await oauth.exchange_code(code)
    me = await oauth.get_me(tokens.access_token)

    user = await users.upsert(
        discord_id=me.discord_id,
        username=me.username,
        avatar_url=me.avatar_url,
        access_token_enc=encrypt_str(tokens.access_token),
        refresh_token_enc=encrypt_str(tokens.refresh_token),
        token_expires_at=tokens.expires_at,
    )

    session = create_session_token(user.id)
    resp = RedirectResponse(url=f"{settings.FRONTEND_URL}/dashboard", status_code=307)
    resp.delete_cookie(STATE_COOKIE, path="/")
    resp.set_cookie(
        SESSION_COOKIE,
        session,
        max_age=settings.JWT_TTL_MINUTES * 60,
        httponly=True,
        secure=False,
        samesite="lax",
        path="/",
    )
    return resp


@router.post("/logout", status_code=204)
async def logout():
    resp = Response(status_code=204)
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp
