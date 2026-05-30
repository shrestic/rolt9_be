from datetime import UTC, datetime, timedelta

import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response

from app.core.config import settings
from app.core.crypto import encrypt_str
from app.core.security import create_session_token
from app.main import app
from app.models.user import User
from app.repositories.guild import GuildRepository
from app.repositories.guild_settings import GuildSettingsRepository

GUILDS_URL = "https://discord.com/api/users/@me/guilds"
GID = 77


@pytest.fixture
def seed(db_session):
    async def _seed():
        u = User(
            discord_id=888,
            username="bob",
            avatar_url=None,
            access_token_enc=encrypt_str("AT"),
            refresh_token_enc=encrypt_str("RT"),
            token_expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        db_session.add(u)
        await db_session.commit()
        await db_session.refresh(u)
        g = await GuildRepository(db_session).upsert(
            discord_id=GID, name="KarmaGuild", icon_url=None
        )
        await GuildSettingsRepository(db_session).create_defaults(g.id)
        client = TestClient(app, cookies={"rolt9_session": create_session_token(u.id)})
        return client, g

    return _seed


def _mock_owned():
    respx.get(GUILDS_URL).mock(
        return_value=Response(
            200,
            json=[
                {
                    "id": str(GID),
                    "name": "KarmaGuild",
                    "icon": None,
                    "owner": True,
                    "permissions": "0",
                }
            ],
        )
    )


def _url_settings() -> str:
    return f"{settings.API_V1_STR}/guilds/{GID}/karma/settings"


def _url_leaderboard() -> str:
    return f"{settings.API_V1_STR}/guilds/{GID}/karma/leaderboard"


@pytest.mark.asyncio
@respx.mock
async def test_get_settings_defaults(seed):
    client, _ = await seed()
    _mock_owned()
    r = client.get(_url_settings())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is False


@pytest.mark.asyncio
@respx.mock
async def test_put_settings_round_trips(seed):
    client, _ = await seed()
    _mock_owned()
    r = client.put(_url_settings(), json={"enabled": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is True


@pytest.mark.asyncio
@respx.mock
async def test_get_leaderboard_empty(seed):
    client, _ = await seed()
    _mock_owned()
    r = client.get(_url_leaderboard(), params={"page": 1, "page_size": 20})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "items" in body
    assert "total" in body
    assert "page" in body
    assert "page_size" in body
