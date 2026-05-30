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
GID = 88


@pytest.fixture
def seed(db_session):
    async def _seed():
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
        g = await GuildRepository(db_session).upsert(discord_id=GID, name="S", icon_url=None)
        await GuildSettingsRepository(db_session).create_defaults(g.id)
        client = TestClient(app, cookies={"rolt9_session": create_session_token(u.id)})
        return client, g

    return _seed


def _mock_owned():
    respx.get(GUILDS_URL).mock(
        return_value=Response(
            200,
            json=[{"id": str(GID), "name": "S", "icon": None, "owner": True, "permissions": "0"}],
        )
    )


def _settings_url() -> str:
    return f"{settings.API_V1_STR}/guilds/{GID}/pet/settings"


def _status_url() -> str:
    return f"{settings.API_V1_STR}/guilds/{GID}/pet/status"


@pytest.mark.asyncio
@respx.mock
async def test_get_settings_defaults(seed):
    """GET /pet/settings returns 200 with sane defaults for an unconfigured guild."""
    client, _ = await seed()
    _mock_owned()
    r = client.get(_settings_url())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is False
    assert body["name"] == "Pet"


@pytest.mark.asyncio
@respx.mock
async def test_put_settings_persists(seed):
    """PUT /pet/settings 200-round-trips the full payload back in the response."""
    client, _ = await seed()
    _mock_owned()
    payload = {
        "enabled": True,
        "name": "Rex",
        "feed_cost": 25,
        "feed_amount": 30,
        "play_amount": 30,
        "decay_per_day": 20,
    }
    r = client.put(_settings_url(), json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is True
    assert body["name"] == "Rex"
    assert body["feed_cost"] == 25


@pytest.mark.asyncio
@respx.mock
async def test_get_status(seed):
    """GET /pet/status returns 200 with required top-level keys."""
    client, _ = await seed()
    _mock_owned()
    r = client.get(_status_url())
    assert r.status_code == 200, r.text
    body = r.json()
    for key in ("hunger", "happiness", "level", "stage_emoji", "enabled"):
        assert key in body, f"missing key: {key}"
