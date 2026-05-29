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
from app.repositories.guild_rank_card_theme import GuildRankCardThemeRepository
from app.repositories.guild_settings import GuildSettingsRepository

GUILDS_URL = "https://discord.com/api/users/@me/guilds"
GID = 85


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


def _url() -> str:
    return f"{settings.API_V1_STR}/guilds/{GID}/leveling/rank-card-theme"


@pytest.mark.asyncio
@respx.mock
async def test_get_theme_returns_defaults(seed):
    client, _ = await seed()
    _mock_owned()
    r = client.get(_url())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["bg_type"] == "gradient"
    assert body["bg_color_1"] == "#0f172a"
    assert body["bg_color_2"] == "#581c87"
    assert body["accent_color"] == "#fbbf24"
    assert body["text_color"] == "#ffffff"


@pytest.mark.asyncio
@respx.mock
async def test_put_theme_persists(seed, db_session):
    client, g = await seed()
    _mock_owned()
    payload = {
        "bg_type": "solid",
        "bg_color_1": "#123456",
        "bg_color_2": "#581c87",
        "accent_color": "#fbbf24",
        "text_color": "#ffffff",
    }
    r = client.put(_url(), json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["bg_type"] == "solid"
    assert body["bg_color_1"] == "#123456"

    # Verify persistence in DB.
    t = await GuildRankCardThemeRepository(db_session).get(g.id)
    assert t is not None
    assert t.bg_type == "solid"
    assert t.bg_color_1 == "#123456"


@pytest.mark.asyncio
@respx.mock
async def test_put_theme_rejects_unknown_bg_type(seed):
    client, _ = await seed()
    _mock_owned()
    payload = {
        "bg_type": "image",
        "bg_color_1": "#0f172a",
        "bg_color_2": "#581c87",
        "accent_color": "#fbbf24",
        "text_color": "#ffffff",
    }
    r = client.put(_url(), json=payload)
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
@respx.mock
async def test_put_theme_rejects_invalid_hex(seed):
    client, _ = await seed()
    _mock_owned()
    payload = {
        "bg_type": "gradient",
        "bg_color_1": "not-a-hex",
        "bg_color_2": "#581c87",
        "accent_color": "#fbbf24",
        "text_color": "#ffffff",
    }
    r = client.put(_url(), json=payload)
    assert r.status_code == 422, r.text
