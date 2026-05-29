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
from app.repositories.user_xp import UserXpRepository

GUILDS_URL = "https://discord.com/api/users/@me/guilds"
GID = 83


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


def _member_url(user_id: int) -> str:
    return f"{settings.API_V1_STR}/guilds/{GID}/leveling/members/{user_id}"


@pytest.mark.asyncio
@respx.mock
async def test_get_member_returns_zero_for_unknown(seed):
    client, _ = await seed()
    _mock_owned()
    r = client.get(_member_url(424242))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user_id"] == "424242"
    assert body["total_xp"] == 0
    assert body["level"] == 0
    assert body["rank"] == 0
    assert body["xp_into_level"] == 0
    assert body["xp_for_next_level"] == 100


@pytest.mark.asyncio
@respx.mock
async def test_patch_member_sets_xp(seed, db_session):
    client, g = await seed()
    _mock_owned()
    uid = 555
    r = client.patch(_member_url(uid), json={"total_xp": 250})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user_id"] == str(uid)
    assert body["total_xp"] == 250
    assert body["level"] >= 1
    # Side effect: persisted in DB.
    row = await UserXpRepository(db_session).get(g.id, uid)
    assert row is not None
    assert row.total_xp == 250


@pytest.mark.asyncio
@respx.mock
async def test_patch_member_rejects_negative_xp(seed):
    client, _ = await seed()
    _mock_owned()
    r = client.patch(_member_url(556), json={"total_xp": -10})
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
@respx.mock
async def test_delete_member_resets(seed, db_session):
    client, g = await seed()
    repo = UserXpRepository(db_session)
    uid = 777
    await repo.set_xp(g.id, user_id=uid, total_xp=500)

    _mock_owned()
    r = client.delete(_member_url(uid))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user_id"] == str(uid)
    assert body["total_xp"] == 0
    assert body["level"] == 0

    # Subsequent GET also reports zero.
    r2 = client.get(_member_url(uid))
    assert r2.status_code == 200, r2.text
    assert r2.json()["total_xp"] == 0
    assert r2.json()["level"] == 0

    # And the row is gone from the DB.
    assert await repo.get(g.id, uid) is None
