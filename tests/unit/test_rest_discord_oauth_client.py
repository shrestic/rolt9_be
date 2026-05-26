# Smoke tests for RestDiscordOAuthClient — covers OAuth flow + the OAuth error
# normalization at the httpx boundary. Bot-side actions (ban/kick/post/etc.)
# now live in BotDiscordClient and are exercised via integration tests using
# FakeDiscordClient.

import httpx
import pytest
import respx
from httpx import Response

from app.discord_io.clients.rest import RestDiscordOAuthClient
from app.discord_io.errors import (
    DiscordError,
    DiscordForbidden,
    DiscordNotFound,
    DiscordRateLimited,
)


def _client() -> RestDiscordOAuthClient:
    return RestDiscordOAuthClient(http=httpx.AsyncClient())


@pytest.mark.asyncio
@respx.mock
async def test_oauth_exchange_returns_tokens():
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
    tokens = await _client().exchange_oauth_code("code123")
    assert tokens.access_token == "AT"
    assert tokens.refresh_token == "RT"


@pytest.mark.asyncio
@respx.mock
async def test_oauth_refresh_returns_new_tokens():
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
    tokens = await _client().refresh_oauth_token("OLD-RT")
    assert tokens.access_token == "AT2"


@pytest.mark.asyncio
@respx.mock
async def test_get_user_me_returns_user_info():
    respx.get("https://discord.com/api/users/@me").mock(
        return_value=Response(200, json={"id": "111", "username": "alice", "avatar": "abc"})
    )
    me = await _client().get_user_me("AT")
    assert me.discord_id == 111
    assert me.username == "alice"
    assert me.avatar_url is not None and me.avatar_url.endswith("/abc.png")


@pytest.mark.asyncio
@respx.mock
async def test_list_guilds_of_user_parses_each_entry():
    respx.get("https://discord.com/api/users/@me/guilds").mock(
        return_value=Response(
            200,
            json=[
                {"id": "1", "name": "A", "icon": None, "owner": True, "permissions": "0"},
                {"id": "2", "name": "B", "icon": None, "owner": False, "permissions": "32"},
            ],
        )
    )
    guilds = await _client().list_guilds_of_user("AT")
    assert len(guilds) == 2
    assert guilds[0].owner is True
    assert guilds[1].permissions == 32


# ── Error normalization (using OAuth endpoints as the test surface) ──


@pytest.mark.asyncio
@respx.mock
async def test_404_raises_not_found():
    respx.get("https://discord.com/api/users/@me").mock(return_value=Response(404))
    with pytest.raises(DiscordNotFound):
        await _client().get_user_me("AT")


@pytest.mark.asyncio
@respx.mock
async def test_403_raises_forbidden():
    respx.get("https://discord.com/api/users/@me").mock(return_value=Response(403))
    with pytest.raises(DiscordForbidden):
        await _client().get_user_me("AT")


@pytest.mark.asyncio
@respx.mock
async def test_429_raises_rate_limited_with_retry_after():
    respx.get("https://discord.com/api/users/@me").mock(
        return_value=Response(429, json={"retry_after": 1.5})
    )
    with pytest.raises(DiscordRateLimited) as ei:
        await _client().get_user_me("AT")
    assert ei.value.retry_after_seconds == 1.5


@pytest.mark.asyncio
@respx.mock
async def test_500_raises_generic_error():
    respx.get("https://discord.com/api/users/@me").mock(return_value=Response(500))
    with pytest.raises(DiscordError):
        await _client().get_user_me("AT")
