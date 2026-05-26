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
from app.repositories.mod_case import ModCaseRepository

GUILDS_URL = "https://discord.com/api/users/@me/guilds"
GID = 55


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


@pytest.mark.asyncio
@respx.mock
async def test_get_then_update_settings(seed):
    client, _ = await seed()
    _mock_owned()
    r = client.get(f"{settings.API_V1_STR}/guilds/{GID}/moderation")
    assert r.status_code == 200, r.text
    assert r.json()["dm_on_action"] is True

    body = {
        "mod_log_channel_id": "123",
        "dm_on_action": False,
        "warn_escalation": [{"threshold": 3, "action": "mute", "duration_seconds": 3600}],
    }
    r2 = client.put(f"{settings.API_V1_STR}/guilds/{GID}/moderation", json=body)
    assert r2.status_code == 200, r2.text
    assert r2.json()["mod_log_channel_id"] == "123"
    assert r2.json()["warn_escalation"][0]["threshold"] == 3


@pytest.mark.asyncio
@respx.mock
async def test_list_cases_filtered(seed, db_session):
    client, g = await seed()
    repo = ModCaseRepository(db_session)
    base = {
        "source": "manual",
        "target_username": "t",
        "moderator_user_id": 1,
        "moderator_username": "m",
        "reason": None,
    }
    await repo.create_case(guild_id=g.id, action="warn", target_user_id=7, **base)
    await repo.create_case(guild_id=g.id, action="ban", target_user_id=7, **base)
    _mock_owned()
    r = client.get(f"{settings.API_V1_STR}/guilds/{GID}/cases?action=warn")
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["action"] == "warn"
    assert r.json()["items"][0]["target_user_id"] == "7"


@pytest.mark.asyncio
@respx.mock
async def test_deactivate_case(seed, db_session):
    client, g = await seed()
    c = await ModCaseRepository(db_session).create_case(
        guild_id=g.id,
        action="warn",
        source="manual",
        target_user_id=7,
        target_username="t",
        moderator_user_id=1,
        moderator_username="m",
        reason=None,
    )
    _mock_owned()
    r = client.delete(f"{settings.API_V1_STR}/guilds/{GID}/cases/{c.case_number}")
    assert r.status_code == 200, r.text
    assert r.json()["active"] is False


@pytest.mark.asyncio
@respx.mock
async def test_deactivate_ban_revokes_discord_ban(seed, db_session, fake_discord):
    client, g = await seed()
    c = await ModCaseRepository(db_session).create_case(
        guild_id=g.id,
        action="ban",
        source="manual",
        target_user_id=7,
        target_username="t",
        moderator_user_id=1,
        moderator_username="m",
        reason=None,
    )
    _mock_owned()
    # Pre-seed the fake with the ban so revoke_ban has something to remove.
    fake_discord.bans.add((GID, 7))
    r = client.delete(f"{settings.API_V1_STR}/guilds/{GID}/cases/{c.case_number}")
    assert r.status_code == 200, r.text
    assert r.json()["active"] is False
    # The ban was revoked through the bot client (FakeDiscordClient).
    assert (GID, 7) not in fake_discord.bans


@pytest.mark.asyncio
@respx.mock
async def test_deactivate_ban_ok_when_already_unbanned(seed, db_session, fake_discord):
    client, g = await seed()
    c = await ModCaseRepository(db_session).create_case(
        guild_id=g.id,
        action="ban",
        source="manual",
        target_user_id=8,
        target_username="t",
        moderator_user_id=1,
        moderator_username="m",
        reason=None,
    )
    _mock_owned()
    # No pre-seeded ban — revoke_ban is idempotent and treats this as success.
    r = client.delete(f"{settings.API_V1_STR}/guilds/{GID}/cases/{c.case_number}")
    assert r.status_code == 200, r.text
    assert r.json()["active"] is False


@pytest.mark.asyncio
@respx.mock
async def test_deactivate_warn_does_not_call_discord(seed, db_session, fake_discord):
    client, g = await seed()
    c = await ModCaseRepository(db_session).create_case(
        guild_id=g.id,
        action="warn",
        source="manual",
        target_user_id=9,
        target_username="t",
        moderator_user_id=1,
        moderator_username="m",
        reason=None,
    )
    _mock_owned()
    # Pre-seed a ban for an unrelated user to detect any accidental revoke.
    fake_discord.bans.add((GID, 9))
    r = client.delete(f"{settings.API_V1_STR}/guilds/{GID}/cases/{c.case_number}")
    assert r.status_code == 200, r.text
    assert r.json()["active"] is False
    # A warn deactivation must NOT touch Discord — the ban stays.
    assert (GID, 9) in fake_discord.bans


@pytest.mark.asyncio
@respx.mock
async def test_non_manager_403(seed):
    client, _ = await seed()
    respx.get(GUILDS_URL).mock(
        return_value=Response(
            200,
            json=[{"id": str(GID), "name": "S", "icon": None, "owner": False, "permissions": "0"}],
        )
    )
    r = client.get(f"{settings.API_V1_STR}/guilds/{GID}/moderation")
    assert r.status_code == 403
