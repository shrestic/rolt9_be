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
from app.repositories.leveling_config import GuildLevelingConfigRepository

GUILDS_URL = "https://discord.com/api/users/@me/guilds"
GID = 81


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
    return f"{settings.API_V1_STR}/guilds/{GID}/leveling/settings"


@pytest.mark.asyncio
@respx.mock
async def test_get_settings_returns_defaults(seed):
    client, _ = await seed()
    _mock_owned()
    r = client.get(_url())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is False
    assert body["xp_min"] == 15
    assert body["xp_max"] == 25
    assert body["cooldown_seconds"] == 60
    assert body["min_message_length"] == 4
    assert body["ignore_emoji_only"] is True
    assert body["ignore_link_only"] is True
    assert body["ignored_channel_ids"] == []
    assert body["ignored_role_ids"] == []
    assert body["notification_mode"] == "channel"
    assert body["notification_channel_id"] is None
    assert body["level_role_mode"] == "replacing"


@pytest.mark.asyncio
@respx.mock
async def test_put_settings_persists_and_returns(seed, db_session):
    client, g = await seed()
    _mock_owned()
    payload = {
        "enabled": True,
        "xp_min": 10,
        "xp_max": 40,
        "cooldown_seconds": 90,
        "min_message_length": 6,
        "ignore_emoji_only": False,
        "ignore_link_only": False,
        "ignored_channel_ids": ["111", "222"],
        "ignored_role_ids": ["333"],
        "notification_mode": "channel",
        "notification_channel_id": "444",
        "level_role_mode": "stacking",
    }
    r = client.put(_url(), json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is True
    assert body["xp_min"] == 10
    assert body["xp_max"] == 40
    assert body["cooldown_seconds"] == 90
    assert body["min_message_length"] == 6
    assert body["ignore_emoji_only"] is False
    assert body["ignore_link_only"] is False
    assert body["ignored_channel_ids"] == ["111", "222"]
    assert body["ignored_role_ids"] == ["333"]
    assert body["notification_mode"] == "channel"
    assert body["notification_channel_id"] == "444"
    assert body["level_role_mode"] == "stacking"

    # Verify persistence in DB via repository lookup.
    cfg = await GuildLevelingConfigRepository(db_session).get(g.id)
    assert cfg is not None
    assert cfg.enabled is True
    assert cfg.xp_min == 10
    assert cfg.xp_max == 40
    assert cfg.notification_channel_id == 444
    assert cfg.ignored_channel_ids == [111, 222]
    assert cfg.ignored_role_ids == [333]
    assert cfg.level_role_mode == "stacking"


@pytest.mark.asyncio
@respx.mock
async def test_put_settings_rejects_xp_min_gt_max(seed):
    client, _ = await seed()
    _mock_owned()
    payload = {
        "enabled": False,
        "xp_min": 50,
        "xp_max": 20,
        "cooldown_seconds": 60,
        "min_message_length": 4,
        "ignore_emoji_only": True,
        "ignore_link_only": True,
        "ignored_channel_ids": [],
        "ignored_role_ids": [],
        "notification_mode": "channel",
        "notification_channel_id": None,
        "level_role_mode": "replacing",
    }
    r = client.put(_url(), json=payload)
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
@respx.mock
async def test_put_settings_requires_channel_id_when_enabled_and_channel_mode(seed):
    client, _ = await seed()
    _mock_owned()
    payload = {
        "enabled": True,
        "xp_min": 15,
        "xp_max": 25,
        "cooldown_seconds": 60,
        "min_message_length": 4,
        "ignore_emoji_only": True,
        "ignore_link_only": True,
        "ignored_channel_ids": [],
        "ignored_role_ids": [],
        "notification_mode": "channel",
        "notification_channel_id": None,
        "level_role_mode": "replacing",
    }
    r = client.put(_url(), json=payload)
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
@respx.mock
async def test_put_settings_allows_channel_mode_without_channel_when_disabled(seed):
    # The validator is conditional on `enabled` — admins can stage
    # mode='channel' with a NULL channel before flipping the master switch.
    client, _ = await seed()
    _mock_owned()
    payload = {
        "enabled": False,
        "xp_min": 15,
        "xp_max": 25,
        "cooldown_seconds": 60,
        "min_message_length": 4,
        "ignore_emoji_only": True,
        "ignore_link_only": True,
        "ignored_channel_ids": [],
        "ignored_role_ids": [],
        "notification_mode": "channel",
        "notification_channel_id": None,
        "level_role_mode": "replacing",
    }
    r = client.put(_url(), json=payload)
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
@respx.mock
async def test_get_settings_forbidden_for_non_manager(seed):
    client, _ = await seed()
    respx.get(GUILDS_URL).mock(
        return_value=Response(
            200,
            json=[{"id": str(GID), "name": "S", "icon": None, "owner": False, "permissions": "0"}],
        )
    )
    r = client.get(_url())
    assert r.status_code == 403


@pytest.mark.asyncio
@respx.mock
async def test_get_settings_includes_decay_defaults(seed):
    client, _ = await seed()
    _mock_owned()
    r = client.get(_url())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["xp_decay_enabled"] is False
    assert body["xp_decay_percent"] == 10
    assert body["xp_decay_inactivity_days"] == 7


@pytest.mark.asyncio
@respx.mock
async def test_put_settings_persists_decay_fields(seed, db_session):
    client, g = await seed()
    _mock_owned()
    payload = {
        "enabled": False,
        "xp_min": 15,
        "xp_max": 25,
        "cooldown_seconds": 60,
        "min_message_length": 4,
        "ignore_emoji_only": True,
        "ignore_link_only": True,
        "ignored_channel_ids": [],
        "ignored_role_ids": [],
        "notification_mode": "channel",
        "notification_channel_id": None,
        "level_role_mode": "replacing",
        "xp_decay_enabled": True,
        "xp_decay_percent": 25,
        "xp_decay_inactivity_days": 14,
    }
    r = client.put(_url(), json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["xp_decay_enabled"] is True
    assert body["xp_decay_percent"] == 25
    assert body["xp_decay_inactivity_days"] == 14

    from app.repositories.leveling_config import GuildLevelingConfigRepository

    cfg = await GuildLevelingConfigRepository(db_session).get(g.id)
    assert cfg.xp_decay_enabled is True
    assert cfg.xp_decay_percent == 25
    assert cfg.xp_decay_inactivity_days == 14


@pytest.mark.asyncio
@respx.mock
async def test_put_settings_rejects_bad_decay_values(seed):
    client, _ = await seed()
    _mock_owned()
    base = {
        "enabled": False,
        "xp_min": 15,
        "xp_max": 25,
        "cooldown_seconds": 60,
        "min_message_length": 4,
        "ignore_emoji_only": True,
        "ignore_link_only": True,
        "ignored_channel_ids": [],
        "ignored_role_ids": [],
        "notification_mode": "channel",
        "notification_channel_id": None,
        "level_role_mode": "replacing",
        "xp_decay_enabled": True,
        "xp_decay_percent": 10,
        "xp_decay_inactivity_days": 7,
    }
    r = client.put(_url(), json={**base, "xp_decay_percent": 0})
    assert r.status_code == 422, r.text
    r = client.put(_url(), json={**base, "xp_decay_percent": 101})
    assert r.status_code == 422, r.text
    r = client.put(_url(), json={**base, "xp_decay_inactivity_days": 0})
    assert r.status_code == 422, r.text
