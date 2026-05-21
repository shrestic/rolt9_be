from datetime import UTC, datetime, timedelta

import pytest
import respx
from httpx import Response

from app.services.discord_oauth import DiscordOAuthService


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code_returns_tokens():
    respx.post("https://discord.com/api/oauth2/token").mock(
        return_value=Response(
            200,
            json={
                "access_token": "AT",
                "refresh_token": "RT",
                "expires_in": 3600,
                "token_type": "Bearer",
                "scope": "identify guilds",
            },
        )
    )
    respx.get("https://discord.com/api/users/@me").mock(
        return_value=Response(
            200,
            json={"id": "111", "username": "alice", "avatar": "abc"},
        )
    )

    svc = DiscordOAuthService()
    tokens = await svc.exchange_code("the-code")
    me = await svc.get_me(tokens.access_token)

    assert tokens.access_token == "AT"
    assert tokens.refresh_token == "RT"
    assert tokens.expires_at > datetime.now(UTC)
    assert me.discord_id == 111
    assert me.username == "alice"
    assert me.avatar_url.endswith("/abc.png")


@pytest.mark.asyncio
@respx.mock
async def test_refresh_token_updates_expiry():
    respx.post("https://discord.com/api/oauth2/token").mock(
        return_value=Response(
            200,
            json={
                "access_token": "AT2",
                "refresh_token": "RT2",
                "expires_in": 7200,
                "token_type": "Bearer",
                "scope": "identify guilds",
            },
        )
    )

    svc = DiscordOAuthService()
    tokens = await svc.refresh("OLD-RT")
    assert tokens.access_token == "AT2"
    assert tokens.refresh_token == "RT2"


@pytest.mark.asyncio
@respx.mock
async def test_get_valid_access_token_returns_existing_when_not_near_expiry(db_session):
    from app.core.crypto import encrypt_str
    from app.models.user import User
    from app.repositories.user import UserRepository

    u = User(
        discord_id=1,
        username="a",
        avatar_url=None,
        access_token_enc=encrypt_str("STILL-GOOD"),
        refresh_token_enc=encrypt_str("RT"),
        token_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)

    route = respx.post("https://discord.com/api/oauth2/token").mock(
        return_value=Response(200, json={})
    )
    svc = DiscordOAuthService()
    token = await svc.get_valid_access_token(u, UserRepository(db_session))
    assert token == "STILL-GOOD"
    assert route.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_get_valid_access_token_refreshes_when_near_expiry(db_session):
    from app.core.crypto import decrypt_str, encrypt_str
    from app.models.user import User
    from app.repositories.user import UserRepository

    u = User(
        discord_id=1,
        username="a",
        avatar_url=None,
        access_token_enc=encrypt_str("OLD"),
        refresh_token_enc=encrypt_str("RT-OLD"),
        token_expires_at=datetime.now(UTC) + timedelta(seconds=30),  # within 60s
    )
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)

    respx.post("https://discord.com/api/oauth2/token").mock(
        return_value=Response(
            200,
            json={
                "access_token": "NEW",
                "refresh_token": "RT-NEW",
                "expires_in": 3600,
                "token_type": "Bearer",
                "scope": "identify guilds",
            },
        )
    )

    svc = DiscordOAuthService()
    token = await svc.get_valid_access_token(u, UserRepository(db_session))
    assert token == "NEW"

    refreshed = await UserRepository(db_session).get_by_id(u.id)
    assert decrypt_str(refreshed.access_token_enc) == "NEW"
    assert decrypt_str(refreshed.refresh_token_enc) == "RT-NEW"
