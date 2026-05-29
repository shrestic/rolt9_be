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
from app.repositories.user_wallet import WalletRepository

GUILDS_URL = "https://discord.com/api/users/@me/guilds"
GID = 89


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
        await WalletRepository(db_session).set_balance(g.id, 1, 500)
        await WalletRepository(db_session).set_balance(g.id, 2, 200)
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
async def test_leaderboard(seed):
    client, _ = await seed()
    _mock_owned()
    r = client.get(f"{settings.API_V1_STR}/guilds/{GID}/currency/leaderboard")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert [i["user_id"] for i in items] == ["1", "2"]
    assert items[0]["balance"] == 500


@pytest.mark.asyncio
@respx.mock
async def test_get_set_reset_member(seed, db_session):
    client, g = await seed()
    _mock_owned()
    base = f"{settings.API_V1_STR}/guilds/{GID}/currency/members/1"
    assert client.get(base).json()["balance"] == 500
    assert client.patch(base, json={"balance": 1000}).status_code == 200
    assert (await WalletRepository(db_session).get(g.id, 1)).balance == 1000
    assert client.delete(base).status_code == 200
    assert (await WalletRepository(db_session).get(g.id, 1)).balance == 0
