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
from app.repositories.level_role_reward import LevelRoleRewardRepository

GUILDS_URL = "https://discord.com/api/users/@me/guilds"
GID = 84


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


def _rewards_url() -> str:
    return f"{settings.API_V1_STR}/guilds/{GID}/leveling/rewards"


@pytest.mark.asyncio
@respx.mock
async def test_create_then_list_then_delete(seed, db_session):
    client, g = await seed()
    _mock_owned()

    # POST: create a reward.
    r = client.post(_rewards_url(), json={"level": 5, "role_id": "9001"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"level": 5, "role_id": "9001"}

    # GET list: contains the new reward.
    r2 = client.get(_rewards_url())
    assert r2.status_code == 200
    items = r2.json()
    assert items == [{"level": 5, "role_id": "9001"}]

    # DELETE: remove it.
    r3 = client.delete(f"{_rewards_url()}/5")
    assert r3.status_code == 200, r3.text
    assert r3.json() == {"level": 5, "role_id": "9001"}

    # GET list: now empty.
    r4 = client.get(_rewards_url())
    assert r4.status_code == 200
    assert r4.json() == []

    # And the DB confirms the deletion.
    repo = LevelRoleRewardRepository(db_session)
    assert await repo.list_by_guild(g.id) == []


@pytest.mark.asyncio
@respx.mock
async def test_delete_unknown_level_404(seed):
    client, _ = await seed()
    _mock_owned()
    r = client.delete(f"{_rewards_url()}/99")
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
@respx.mock
async def test_post_replaces_existing_role_for_same_level(seed, db_session):
    client, g = await seed()
    _mock_owned()

    # First POST → creates the reward.
    r1 = client.post(_rewards_url(), json={"level": 10, "role_id": "1111"})
    assert r1.status_code == 200, r1.text
    assert r1.json() == {"level": 10, "role_id": "1111"}

    # Second POST at same level → upserts, replacing the role.
    r2 = client.post(_rewards_url(), json={"level": 10, "role_id": "2222"})
    assert r2.status_code == 200, r2.text
    assert r2.json() == {"level": 10, "role_id": "2222"}

    # Only one row exists, with the new role_id (UNIQUE constraint behavior).
    rows = await LevelRoleRewardRepository(db_session).list_by_guild(g.id)
    assert len(rows) == 1
    assert rows[0].level == 10
    assert rows[0].role_id == 2222


@pytest.mark.asyncio
@respx.mock
async def test_create_reward_rejects_invalid_level(seed):
    client, _ = await seed()
    _mock_owned()
    # level must be in [1, 500].
    r = client.post(_rewards_url(), json={"level": 0, "role_id": "777"})
    assert r.status_code == 422, r.text
