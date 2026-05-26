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
GID = 77


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


def _base(prefix="/guilds"):
    return f"{settings.API_V1_STR}{prefix}/{GID}"


@pytest.mark.asyncio
@respx.mock
async def test_create_and_list(seed):
    client, _ = await seed()
    _mock_owned()
    r = client.post(
        f"{_base()}/commands",
        json={"trigger": "Rules", "response_type": "text", "response_text": "Be nice {user}"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["trigger"] == "rules"
    r2 = client.get(f"{_base()}/commands")
    assert r2.status_code == 200
    assert len(r2.json()) == 1


@pytest.mark.asyncio
@respx.mock
async def test_duplicate_trigger_409(seed):
    client, _ = await seed()
    _mock_owned()
    body = {"trigger": "rules", "response_type": "text", "response_text": "x"}
    assert client.post(f"{_base()}/commands", json=body).status_code == 201
    assert client.post(f"{_base()}/commands", json=body).status_code == 409


@pytest.mark.asyncio
@respx.mock
async def test_validation_error_422(seed):
    client, _ = await seed()
    _mock_owned()
    # response_type text but no response_text
    r = client.post(f"{_base()}/commands", json={"trigger": "x", "response_type": "text"})
    assert r.status_code == 422


@pytest.mark.asyncio
@respx.mock
async def test_update_and_delete(seed):
    client, _ = await seed()
    _mock_owned()
    created = client.post(
        f"{_base()}/commands",
        json={"trigger": "a", "response_type": "text", "response_text": "x"},
    ).json()
    cid = created["id"]
    upd = client.put(
        f"{_base()}/commands/{cid}",
        json={"trigger": "a", "response_type": "text", "response_text": "z"},
    )
    assert upd.status_code == 200, upd.text
    assert upd.json()["response_text"] == "z"
    assert client.delete(f"{_base()}/commands/{cid}").status_code == 204
    assert client.get(f"{_base()}/commands/{cid}").status_code == 404


@pytest.mark.asyncio
@respx.mock
async def test_command_settings(seed):
    client, _ = await seed()
    _mock_owned()
    r = client.get(f"{_base()}/command-settings")
    assert r.status_code == 200
    assert r.json()["prefix"] == "!"
    r2 = client.put(f"{_base()}/command-settings", json={"prefix": "?", "enabled": True})
    assert r2.status_code == 200, r2.text
    assert r2.json()["prefix"] == "?"


# ─────────────────────────────────────────────────────────────────────────
# Live preview
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_preview_text_substitutes_placeholders(seed, fake_discord):
    from app.discord_io.types import GuildInfo

    client, _ = await seed()
    _mock_owned()
    # The preview endpoint reads guild name + member_count from the bot's
    # cache, so seed the fake with what we expect to see substituted.
    fake_discord.guilds[GID] = GuildInfo(
        discord_id=GID, name="MyServer", icon_url=None, member_count=250
    )

    r = client.post(
        f"{_base()}/commands/preview",
        json={
            "response_type": "text",
            "response_text": "Hi {user}, welcome to {server} ({member_count} members)",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rendered_text"] == "Hi alice, welcome to MyServer (250 members)"
    assert body["rendered_embed"] is None
    # Placeholder registry comes back with the values used in this render.
    names = {p["name"]: p["example"] for p in body["placeholders"]}
    assert names["user"] == "alice"
    assert names["server"] == "MyServer"
    assert names["member_count"] == "250"
    assert names["user.mention"].startswith("<@")


@pytest.mark.asyncio
@respx.mock
async def test_preview_embed_substitutes_and_resolves_color(seed, fake_discord):
    from app.discord_io.types import GuildInfo

    client, _ = await seed()
    _mock_owned()
    fake_discord.guilds[GID] = GuildInfo(
        discord_id=GID, name="MyServer", icon_url=None, member_count=42
    )

    r = client.post(
        f"{_base()}/commands/preview",
        json={
            "response_type": "embed",
            "embed": {
                "title": "{server} info",
                "description": "We have {member_count} members.",
                "color": "#FF0000",
                "footer": "Powered by rolt9",
            },
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rendered_text"] is None
    embed = body["rendered_embed"]
    assert embed["title"] == "MyServer info"
    assert embed["description"] == "We have 42 members."
    assert embed["color"] == 0xFF0000
    assert embed["footer"] == "Powered by rolt9"


@pytest.mark.asyncio
@respx.mock
async def test_preview_embed_invalid_color_falls_back_to_blurple(seed, fake_discord):
    from app.discord_io.types import GuildInfo

    client, _ = await seed()
    _mock_owned()
    fake_discord.guilds[GID] = GuildInfo(discord_id=GID, name="S", icon_url=None, member_count=1)
    r = client.post(
        f"{_base()}/commands/preview",
        json={
            "response_type": "embed",
            "embed": {"title": "T", "description": "D", "color": "not-a-hex"},
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["rendered_embed"]["color"] == 0x5865F2
