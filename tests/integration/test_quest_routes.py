"""Integration tests for the quest CRUD REST endpoints.

Mirrors the harness in test_currency_settings_routes.py exactly:
  - db_session / seed / TestClient / cookie-based auth
  - respx.mock + _mock_owned() to satisfy require_managed_guild
  - URL prefix from settings.API_V1_STR

Four cases exercise the full CRUD flow:
  1. POST  /          → creates, returns id + sent fields
  2. GET   /          → list contains the created quest
  3. PATCH /{id}      → updates enabled → False
  4. DELETE /{id}     → removes the quest; subsequent GET returns []
"""

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
GID = 77  # distinct from 88 (currency) and 99 (badges) to avoid cross-test pollution

# Canonical quest body used across all cases.
QUEST_BODY = {
    "name": "Earn 500",
    "description": "d",
    "period": "daily",
    "objective_type": "earn_coins",
    "target": 500,
    "reward_coins": 100,
    "enabled": True,
}


@pytest.fixture
def seed(db_session):
    """Seed a user + guild (+ guild_settings defaults) and return a seeded TestClient."""

    async def _seed():
        u = User(
            discord_id=777,
            username="charlie",
            avatar_url=None,
            access_token_enc=encrypt_str("AT"),
            refresh_token_enc=encrypt_str("RT"),
            token_expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        db_session.add(u)
        await db_session.commit()
        await db_session.refresh(u)
        g = await GuildRepository(db_session).upsert(
            discord_id=GID, name="QuestGuild", icon_url=None
        )
        await GuildSettingsRepository(db_session).create_defaults(g.id)
        client = TestClient(app, cookies={"rolt9_session": create_session_token(u.id)})
        return client, g

    return _seed


def _mock_owned():
    """Mock Discord's /users/@me/guilds so require_managed_guild sees GID as owned."""
    respx.get(GUILDS_URL).mock(
        return_value=Response(
            200,
            json=[
                {
                    "id": str(GID),
                    "name": "QuestGuild",
                    "icon": None,
                    "owner": True,
                    "permissions": "0",
                }
            ],
        )
    )


def _list_url() -> str:
    return f"{settings.API_V1_STR}/guilds/{GID}/quests"


def _item_url(quest_id: str) -> str:
    return f"{settings.API_V1_STR}/guilds/{GID}/quests/{quest_id}"


# ─────────────────────────────────────────────────────────────────────────────
# 1. POST / → 200, id present, sent fields echoed back
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_create_quest(seed):
    client, _ = await seed()
    _mock_owned()
    r = client.post(_list_url(), json=QUEST_BODY)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "id" in body
    assert body["name"] == QUEST_BODY["name"]
    assert body["period"] == QUEST_BODY["period"]
    assert body["objective_type"] == QUEST_BODY["objective_type"]
    assert body["target"] == QUEST_BODY["target"]
    assert body["reward_coins"] == QUEST_BODY["reward_coins"]
    assert body["enabled"] is True


# ─────────────────────────────────────────────────────────────────────────────
# 2. GET / → 200, list contains the created quest
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_list_quests_contains_created(seed):
    client, _ = await seed()
    _mock_owned()
    post_r = client.post(_list_url(), json=QUEST_BODY)
    assert post_r.status_code == 200, post_r.text
    created_id = post_r.json()["id"]

    # Each request may re-mock; re-register the mock for the GET call.
    _mock_owned()
    get_r = client.get(_list_url())
    assert get_r.status_code == 200, get_r.text
    ids = [q["id"] for q in get_r.json()]
    assert created_id in ids


# ─────────────────────────────────────────────────────────────────────────────
# 3. PATCH /{quest_id} with enabled: false → 200, enabled is False
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_update_quest_enabled(seed):
    client, _ = await seed()
    _mock_owned()
    post_r = client.post(_list_url(), json=QUEST_BODY)
    assert post_r.status_code == 200, post_r.text
    quest_id = post_r.json()["id"]

    _mock_owned()
    patch_r = client.patch(_item_url(quest_id), json={**QUEST_BODY, "enabled": False})
    assert patch_r.status_code == 200, patch_r.text
    assert patch_r.json()["enabled"] is False


# ─────────────────────────────────────────────────────────────────────────────
# 4. DELETE /{quest_id} → 200; subsequent GET returns []
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_delete_quest(seed):
    client, _ = await seed()
    _mock_owned()
    post_r = client.post(_list_url(), json=QUEST_BODY)
    assert post_r.status_code == 200, post_r.text
    quest_id = post_r.json()["id"]

    _mock_owned()
    del_r = client.delete(_item_url(quest_id))
    assert del_r.status_code == 200, del_r.text

    _mock_owned()
    get_r = client.get(_list_url())
    assert get_r.status_code == 200, get_r.text
    assert get_r.json() == []
