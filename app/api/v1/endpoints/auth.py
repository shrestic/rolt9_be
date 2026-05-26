# OAuth2 flow with Discord:
#   1. GET /auth/discord/login  → redirect to Discord's authorize URL with a state cookie
#   2. User authorizes on Discord → Discord redirects to /auth/discord/callback?code=...&state=...
#   3. Callback exchanges the code for tokens, fetches user info, upserts the
#      user into the DB, and sets a session cookie
#   4. POST /auth/logout → clears the session cookie
#
# Tokens are encrypted before being written to the DB (app.core.crypto). The
# session cookie is a JWT containing user_id.

import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, Cookie, Depends, HTTPException
from fastapi.responses import RedirectResponse, Response

from app.core.config import settings
from app.core.crypto import encrypt_str
from app.core.security import create_session_token
from app.dependencies.services import get_oauth_client, get_user_repository
from app.discord_io.client import DiscordOAuthClient
from app.repositories.user import UserRepository

router = APIRouter()

DISCORD_AUTHORIZE = "https://discord.com/api/oauth2/authorize"
SESSION_COOKIE = "rolt9_session"
STATE_COOKIE = "oauth_state"


# Step 1: redirect the user to Discord's OAuth page.
# The state token is CSRF protection. Discord echoes it back on the callback;
# the callback compares it against the cookie to confirm the request's origin.
@router.get("/discord/login")
async def discord_login():
    state = secrets.token_urlsafe(24)
    params = {
        "client_id": settings.DISCORD_CLIENT_ID,
        "response_type": "code",
        "scope": "identify guilds",  # `identify` = read user info, `guilds` = list user's guilds
        "redirect_uri": settings.DISCORD_REDIRECT_URI,
        "state": state,
        "prompt": "consent",  # force the consent screen (even if the user already authorized)
    }
    resp = RedirectResponse(url=f"{DISCORD_AUTHORIZE}?{urlencode(params)}", status_code=307)
    resp.set_cookie(
        STATE_COOKIE,
        state,
        max_age=600,  # 10 minutes — enough time for the user to click through Discord
        httponly=True,
        secure=False,
        samesite="lax",
        path="/",
    )
    return resp


# Steps 2-3: Discord calls back here with code + state.
# DI: oauth_client + user repo are injected via Depends.
@router.get("/discord/callback")
async def discord_callback(
    code: str,
    state: str,
    oauth_state: str | None = Cookie(default=None),
    oauth: DiscordOAuthClient = Depends(get_oauth_client),
    users: UserRepository = Depends(get_user_repository),
):
    # CSRF check: the state in the URL must match the state cookie.
    if not oauth_state or oauth_state != state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    # Exchange code → tokens (through the client, not direct httpx).
    tokens = await oauth.exchange_oauth_code(code)
    # Fetch info about the user who just authorized.
    me = await oauth.get_user_me(tokens.access_token)

    # Upsert the user into the DB. Tokens are encrypted before storage — a DB
    # compromise will not leak the user's Discord access.
    user = await users.upsert(
        discord_id=me.discord_id,
        username=me.username,
        avatar_url=me.avatar_url,
        access_token_enc=encrypt_str(tokens.access_token),
        refresh_token_enc=encrypt_str(tokens.refresh_token),
        token_expires_at=tokens.expires_at,
    )

    # Issue a session JWT (containing user.id, signed by the BE secret).
    session = create_session_token(user.id)

    # Redirect to the FE dashboard. Delete the state cookie (done), set the
    # session cookie.
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


# Logout = drop the session cookie. The Discord tokens stay in the DB (so the
# user doesn't have to re-authorize next time). To fully revoke, call Discord's
# /oauth2/token/revoke (not implemented yet).
@router.post("/logout", status_code=204)
async def logout():
    resp = Response(status_code=204)
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp
