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
from app.repositories.currency_config import CurrencyConfigRepository
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


def _url() -> str:
    return f"{settings.API_V1_STR}/guilds/{GID}/currency/settings"


@pytest.mark.asyncio
@respx.mock
async def test_get_settings_defaults(seed):
    client, _ = await seed()
    _mock_owned()
    r = client.get(_url())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is False
    assert body["currency_name"] == "coins"
    assert body["earn_min"] == 1
    assert body["earn_max"] == 3
    assert body["daily_amount"] == 100
    assert body["allow_pay"] is True
    # Streak settings should be present with defaults
    assert body["streak_enabled"] is True
    assert body["streak_bonus_per_day"] == 10
    assert body["streak_bonus_cap"] == 500


@pytest.mark.asyncio
@respx.mock
async def test_put_settings_persists(seed, db_session):
    client, g = await seed()
    _mock_owned()
    payload = {
        "enabled": True,
        "currency_name": "xu",
        "currency_emoji": "🪙",
        "earn_min": 2,
        "earn_max": 5,
        "daily_amount": 150,
        "allow_pay": False,
        "streak_enabled": True,
        "streak_bonus_per_day": 25,
        "streak_bonus_cap": 750,
    }
    r = client.put(_url(), json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["currency_name"] == "xu"
    # Streak round-trip: PUT value comes back in the response
    assert body["streak_bonus_per_day"] == 25
    assert body["streak_bonus_cap"] == 750
    assert body["streak_enabled"] is True
    cfg = await CurrencyConfigRepository(db_session).get(g.id)
    assert cfg.enabled is True
    assert cfg.earn_max == 5
    assert cfg.allow_pay is False
    assert cfg.streak_bonus_per_day == 25


@pytest.mark.asyncio
@respx.mock
async def test_put_settings_rejects_bad_values(seed):
    client, _ = await seed()
    _mock_owned()
    base = {
        "enabled": False,
        "currency_name": "coins",
        "currency_emoji": "🪙",
        "earn_min": 1,
        "earn_max": 3,
        "daily_amount": 100,
        "allow_pay": True,
    }
    assert client.put(_url(), json={**base, "earn_min": 9, "earn_max": 2}).status_code == 422
    assert client.put(_url(), json={**base, "earn_max": 10_001}).status_code == 422
    assert client.put(_url(), json={**base, "currency_name": ""}).status_code == 422
