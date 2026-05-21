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
        return TestClient(app, cookies={"rolt9_session": create_session_token(u.id)})

    return _make


@pytest.mark.asyncio
@respx.mock
async def test_overview_returns_data_when_user_manages(make_authed_user_client):
    client = await make_authed_user_client()
    respx.get(GUILDS_URL).mock(
        return_value=Response(
            200,
            json=[
                {"id": "55", "name": "Owned", "icon": None, "owner": True, "permissions": "0"},
            ],
        )
    )
    respx.get("https://discord.com/api/guilds/55").mock(
        return_value=Response(
            200,
            json={
                "id": "55",
                "name": "Owned",
                "icon": None,
                "approximate_member_count": 42,
            },
        )
    )
    respx.get("https://discord.com/api/guilds/55/channels").mock(
        return_value=Response(
            200,
            json=[
                {"id": "100", "name": "general", "type": 0},
            ],
        )
    )
    respx.get("https://discord.com/api/guilds/55/roles").mock(
        return_value=Response(
            200,
            json=[
                {"id": "1", "name": "@everyone"},
            ],
        )
    )
    r = client.get(f"{settings.API_V1_STR}/guilds/55/overview")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["member_count"] == 42
    assert body["channels"][0]["name"] == "general"


@pytest.mark.asyncio
@respx.mock
async def test_overview_returns_403_when_user_doesnt_manage(make_authed_user_client):
    client = await make_authed_user_client()
    respx.get(GUILDS_URL).mock(
        return_value=Response(
            200,
            json=[
                {"id": "55", "name": "Member", "icon": None, "owner": False, "permissions": "0"},
            ],
        )
    )
    r = client.get(f"{settings.API_V1_STR}/guilds/55/overview")
    assert r.status_code == 403
