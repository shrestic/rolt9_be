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
GID = 82


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
    return f"{settings.API_V1_STR}/guilds/{GID}/leveling/leaderboard"


@pytest.mark.asyncio
@respx.mock
async def test_leaderboard_returns_ordered(seed, db_session):
    client, g = await seed()
    repo = UserXpRepository(db_session)
    # Seed in non-sorted order to ensure ordering comes from the API.
    await repo.set_xp(g.id, user_id=101, total_xp=200)
    await repo.set_xp(g.id, user_id=102, total_xp=800)
    await repo.set_xp(g.id, user_id=103, total_xp=400)

    _mock_owned()
    r = client.get(_url())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 3
    assert body["page"] == 1
    assert body["page_size"] == 20
    items = body["items"]
    assert len(items) == 3
    # Order by total_xp DESC.
    assert items[0]["user_id"] == "102"
    assert items[0]["total_xp"] == 800
    assert items[0]["rank"] == 1
    assert items[1]["user_id"] == "103"
    assert items[1]["total_xp"] == 400
    assert items[1]["rank"] == 2
    assert items[2]["user_id"] == "101"
    assert items[2]["total_xp"] == 200
    assert items[2]["rank"] == 3


@pytest.mark.asyncio
@respx.mock
async def test_leaderboard_pagination(seed, db_session):
    client, g = await seed()
    repo = UserXpRepository(db_session)
    # 4 users with distinct XP — sorted DESC is: 200, 175, 150, 125.
    await repo.set_xp(g.id, user_id=201, total_xp=200)
    await repo.set_xp(g.id, user_id=202, total_xp=175)
    await repo.set_xp(g.id, user_id=203, total_xp=150)
    await repo.set_xp(g.id, user_id=204, total_xp=125)

    _mock_owned()
    r = client.get(_url(), params={"page": 2, "page_size": 2})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 4
    assert body["page"] == 2
    assert body["page_size"] == 2
    items = body["items"]
    assert len(items) == 2
    # Page 2 with size 2 → items 3 and 4 in XP DESC order.
    assert items[0]["user_id"] == "203"
    assert items[0]["total_xp"] == 150
    assert items[0]["rank"] == 3
    assert items[1]["user_id"] == "204"
    assert items[1]["total_xp"] == 125
    assert items[1]["rank"] == 4
