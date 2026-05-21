from datetime import UTC, datetime, timedelta

import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response

from app.core.config import settings
from app.core.security import create_session_token
from app.main import app

GUILDS_URL = "https://discord.com/api/users/@me/guilds"


@pytest.fixture
def make_authed_user_client(db_session):
    """Returns (user, TestClient) for an authed user. Async helper."""
    from app.core.crypto import encrypt_str
    from app.models.user import User

    async def _make():
        u = User(
            discord_id=999,
            username="alice",
            avatar_url=None,
            access_token_enc=encrypt_str("AT"),
            refresh_token_enc=encrypt_str("RT"),
            token_expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        db_session.add(u)
        await db_session.commit()
        await db_session.refresh(u)
        client = TestClient(app, cookies={"rolt9_session": create_session_token(u.id)})
        return u, client

    return _make


@pytest.mark.asyncio
async def test_me_returns_user(make_authed_user_client):
    user, client = await make_authed_user_client()
    r = client.get(f"{settings.API_V1_STR}/me")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["discord_id"] == 999
    assert body["username"] == "alice"


@pytest.mark.asyncio
async def test_me_returns_401_when_unauthenticated():
    client = TestClient(app)
    r = client.get(f"{settings.API_V1_STR}/me")
    assert r.status_code == 401


@pytest.mark.asyncio
@respx.mock
async def test_me_guilds_filters_to_managed_and_marks_bot_present(
    make_authed_user_client, db_session
):
    user, client = await make_authed_user_client()

    respx.get(GUILDS_URL).mock(
        return_value=Response(
            200,
            json=[
                {"id": "10", "name": "A", "icon": None, "owner": True, "permissions": "0"},
                {"id": "20", "name": "B", "icon": None, "owner": False, "permissions": "0"},
                {"id": "30", "name": "C", "icon": None, "owner": False, "permissions": "32"},
            ],
        )
    )

    # Seed guilds: bot is in #10 only.
    from app.repositories.guild import GuildRepository

    await GuildRepository(db_session).upsert(discord_id=10, name="A", icon_url=None)

    r = client.get(f"{settings.API_V1_STR}/me/guilds")
    assert r.status_code == 200, r.text
    body = r.json()
    ids = sorted(g["discord_id"] for g in body)
    assert ids == ["10", "30"]
    present = {g["discord_id"]: g["bot_present"] for g in body}
    assert present["10"] is True
    assert present["30"] is False
