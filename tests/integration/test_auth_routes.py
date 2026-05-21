import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response

from app.core.config import settings
from app.main import app


@pytest.mark.asyncio
async def test_login_redirects_to_discord_authorize():
    client = TestClient(app, follow_redirects=False)
    r = client.get(f"{settings.API_V1_STR}/auth/discord/login")
    assert r.status_code in (302, 307)
    assert "discord.com/api/oauth2/authorize" in r.headers["location"]
    assert "state=" in r.headers["location"]


@pytest.mark.asyncio
@respx.mock
async def test_callback_creates_user_sets_cookie_and_redirects(db_session):
    respx.post("https://discord.com/api/oauth2/token").mock(
        return_value=Response(
            200,
            json={
                "access_token": "AT",
                "refresh_token": "RT",
                "expires_in": 3600,
                "token_type": "Bearer",
                "scope": "identify guilds",
            },
        )
    )
    respx.get("https://discord.com/api/users/@me").mock(
        return_value=Response(200, json={"id": "999", "username": "alice", "avatar": None})
    )

    client = TestClient(app, follow_redirects=False)
    login_resp = client.get(f"{settings.API_V1_STR}/auth/discord/login")
    state_cookie = login_resp.cookies.get("oauth_state")
    state_in_url = login_resp.headers["location"].split("state=")[-1].split("&")[0]
    assert state_cookie == state_in_url

    r = client.get(
        f"{settings.API_V1_STR}/auth/discord/callback",
        params={"code": "the-code", "state": state_in_url},
        cookies={"oauth_state": state_in_url},
    )
    assert r.status_code in (302, 307)
    assert r.headers["location"].startswith(settings.FRONTEND_URL + "/dashboard")
    set_cookie_header = r.headers.get("set-cookie", "")
    assert "rolt9_session=" in set_cookie_header


@pytest.mark.asyncio
async def test_logout_clears_cookie():
    client = TestClient(app)
    r = client.post(f"{settings.API_V1_STR}/auth/logout")
    assert r.status_code == 204
    set_cookie = r.headers.get("set-cookie", "")
    assert 'rolt9_session=""' in set_cookie or "Max-Age=0" in set_cookie
