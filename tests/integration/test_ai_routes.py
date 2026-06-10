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
GID = 79


@pytest.fixture
def seed(db_session):
    async def _seed():
        u = User(
            discord_id=890,
            username="bob",
            avatar_url=None,
            access_token_enc=encrypt_str("AT"),
            refresh_token_enc=encrypt_str("RT"),
            token_expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        db_session.add(u)
        await db_session.commit()
        await db_session.refresh(u)
        g = await GuildRepository(db_session).upsert(discord_id=GID, name="AIGuild", icon_url=None)
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
                    "name": "AIGuild",
                    "icon": None,
                    "owner": True,
                    "permissions": "0",
                }
            ],
        )
    )


def _url() -> str:
    return f"{settings.API_V1_STR}/guilds/{GID}/ai/settings"


@pytest.mark.asyncio
@respx.mock
async def test_get_settings_defaults(seed):
    client, _ = await seed()
    _mock_owned()
    r = client.get(_url())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is False
    assert body["provider"] == ""
    assert body["has_key"] is False
    assert body["key_hint"] == ""
    assert body["tokens_used_this_month"] == 0
    assert float(body["cost_used_this_month"]) == 0.0


@pytest.mark.asyncio
@respx.mock
async def test_put_sets_key_and_hides_it(seed):
    client, _ = await seed()
    _mock_owned()
    r = client.put(
        _url(),
        json={
            "enabled": True,
            "provider": "openai",
            "model": "gpt-5.4-mini",
            "monthly_budget_usd": "12.5",
            "persona": "",
            "api_key": "sk-supersecret",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is True
    assert body["provider"] == "openai"
    assert body["has_key"] is True
    assert body["key_hint"] == "cret"  # last 4 characters
    assert "api_key" not in body  # don't expose the key
    assert float(body["monthly_budget_usd"]) == 12.5


@pytest.mark.asyncio
@respx.mock
async def test_put_invalid_provider_model_is_422(seed):
    client, _ = await seed()
    _mock_owned()
    r = client.put(
        _url(),
        json={
            "enabled": True,
            "provider": "anthropic",
            "model": "gpt-4o",
            "monthly_budget_usd": "5",
            "persona": "",
        },
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
@respx.mock
async def test_put_empty_key_clears_it(seed):
    client, _ = await seed()
    _mock_owned()
    # set the key first
    client.put(
        _url(),
        json={
            "enabled": True,
            "provider": "openai",
            "model": "gpt-5.4-mini",
            "monthly_budget_usd": "5",
            "persona": "",
            "api_key": "sk-abc1234",
        },
    )
    # send "" to clear it
    r = client.put(
        _url(),
        json={
            "enabled": True,
            "provider": "openai",
            "model": "gpt-5.4-mini",
            "monthly_budget_usd": "5",
            "persona": "",
            "api_key": "",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["has_key"] is False


@pytest.mark.asyncio
@respx.mock
async def test_catalog_endpoint(seed):
    client, _ = await seed()
    _mock_owned()
    r = client.get(f"{settings.API_V1_STR}/ai/catalog")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "anthropic" in body
    assert "claude-haiku-4-5" in body["anthropic"]["models"]


@pytest.mark.asyncio
@respx.mock
async def test_put_agent_fields(seed):
    client, _ = await seed()
    _mock_owned()
    r = client.put(
        _url(),
        json={
            "enabled": True,
            "provider": "deepseek",
            "model": "deepseek-chat",
            "monthly_budget_usd": "5",
            "persona": "",
            "agent_enabled": True,
            "agent_channel_id": "123456789",
            "api_key": "sk-x",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["agent_enabled"] is True
    assert body["agent_channel_id"] == "123456789"


@pytest.mark.asyncio
@respx.mock
async def test_put_tools_enabled(seed):
    client, _ = await seed()
    _mock_owned()
    r = client.put(
        _url(),
        json={
            "enabled": True,
            "provider": "deepseek",
            "model": "deepseek-chat",
            "monthly_budget_usd": "5",
            "persona": "",
            "agent_enabled": True,
            "tools_enabled": False,
            "api_key": "sk-x",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["tools_enabled"] is False


@pytest.mark.asyncio
@respx.mock
async def test_put_actions_enabled(seed):
    client, _ = await seed()
    _mock_owned()
    r = client.put(
        _url(),
        json={
            "enabled": True,
            "provider": "deepseek",
            "model": "deepseek-chat",
            "monthly_budget_usd": "5",
            "persona": "",
            "agent_enabled": True,
            "actions_enabled": True,
            "api_key": "sk-x",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["actions_enabled"] is True


@pytest.mark.asyncio
@respx.mock
async def test_put_companion_fields(seed):
    client, _ = await seed()
    _mock_owned()
    r = client.put(
        _url(),
        json={
            "enabled": True,
            "provider": "deepseek",
            "model": "deepseek-chat",
            "monthly_budget_usd": "5",
            "persona": "",
            "companion_enabled": True,
            "companion_channel_id": "987654321",
            "companion_cooldown_min": 30,
            "api_key": "sk-x",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["companion_enabled"] is True
    assert body["companion_channel_id"] == "987654321"
    assert body["companion_cooldown_min"] == 30
