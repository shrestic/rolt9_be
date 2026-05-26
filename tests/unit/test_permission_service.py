import asyncio

import pytest

from app.discord_io.types import UserGuildEntry
from app.services.permission_service import PermissionService
from tests.fakes.discord import FakeOAuthClient


def _oauth_with(*entries: UserGuildEntry) -> FakeOAuthClient:
    f = FakeOAuthClient()
    f.guilds_by_token["AT"] = list(entries)
    return f


@pytest.mark.asyncio
async def test_can_manage_owner_returns_true():
    oauth = _oauth_with(
        UserGuildEntry(discord_id=1, name="A", icon_url=None, owner=True, permissions=0)
    )
    svc = PermissionService(oauth=oauth)
    assert await svc.user_can_manage(access_token="AT", guild_id_str="1") is True


@pytest.mark.asyncio
async def test_can_manage_manage_guild_bit_returns_true():
    oauth = _oauth_with(
        UserGuildEntry(discord_id=2, name="B", icon_url=None, owner=False, permissions=0x20)
    )
    svc = PermissionService(oauth=oauth)
    assert await svc.user_can_manage(access_token="AT", guild_id_str="2") is True


@pytest.mark.asyncio
async def test_can_manage_administrator_returns_true():
    oauth = _oauth_with(
        UserGuildEntry(discord_id=3, name="C", icon_url=None, owner=False, permissions=0x8)
    )
    svc = PermissionService(oauth=oauth)
    assert await svc.user_can_manage(access_token="AT", guild_id_str="3") is True


@pytest.mark.asyncio
async def test_can_manage_member_returns_false():
    oauth = _oauth_with(
        UserGuildEntry(discord_id=4, name="D", icon_url=None, owner=False, permissions=0)
    )
    svc = PermissionService(oauth=oauth)
    assert await svc.user_can_manage(access_token="AT", guild_id_str="4") is False


@pytest.mark.asyncio
async def test_list_my_guilds_filters_to_managed_only():
    oauth = _oauth_with(
        UserGuildEntry(discord_id=1, name="A", icon_url=None, owner=True, permissions=0),
        UserGuildEntry(discord_id=2, name="B", icon_url=None, owner=False, permissions=0),
        UserGuildEntry(discord_id=3, name="C", icon_url=None, owner=False, permissions=0x20),
    )
    svc = PermissionService(oauth=oauth)
    ids = [g.discord_id for g in await svc.list_my_managed_guilds(access_token="AT")]
    assert sorted(ids) == [1, 3]


@pytest.mark.asyncio
async def test_cache_hits_dont_hit_discord_twice():
    oauth = _oauth_with(
        UserGuildEntry(discord_id=1, name="A", icon_url=None, owner=True, permissions=0)
    )
    svc = PermissionService(oauth=oauth)
    await svc.list_my_managed_guilds(access_token="AT")
    await svc.list_my_managed_guilds(access_token="AT")
    assert oauth.list_guilds_calls == 1


@pytest.mark.asyncio
async def test_concurrent_cache_miss_fires_only_one_request():
    # The dashboard loads 4-5 endpoints in parallel that all start cold here.
    # Without single-flight de-dup, every concurrent call would race to Discord
    # and trip the 429 rate limit. Verify that N concurrent callers result in
    # exactly one upstream call.
    #
    # The default fake completes synchronously, which would let the first call
    # populate the cache before the others even start — that wouldn't exercise
    # the race. We subclass with a slow stub so all 5 tasks reach the
    # cache-miss branch before any one of them returns.
    class SlowOAuth(FakeOAuthClient):
        async def list_guilds_of_user(self, access_token: str):  # type: ignore[override]
            self.list_guilds_calls += 1
            await asyncio.sleep(0.05)
            return self.guilds_by_token.get(access_token, [])

    oauth = SlowOAuth()
    oauth.guilds_by_token["AT"] = [
        UserGuildEntry(discord_id=1, name="A", icon_url=None, owner=True, permissions=0)
    ]
    svc = PermissionService(oauth=oauth)
    results = await asyncio.gather(*[svc.list_my_managed_guilds("AT") for _ in range(5)])
    assert oauth.list_guilds_calls == 1
    # All 5 callers got the same result.
    for r in results:
        assert [g.discord_id for g in r] == [1]


@pytest.mark.asyncio
async def test_concurrent_cache_miss_propagates_error_to_all_waiters():
    # If the first in-flight call fails (e.g. Discord 429 / 500), every waiter
    # should also see the error rather than hang forever.
    from app.discord_io.errors import DiscordError

    class FailingOAuth(FakeOAuthClient):
        async def list_guilds_of_user(self, access_token: str):  # type: ignore[override]
            self.list_guilds_calls += 1
            await asyncio.sleep(0.02)
            raise DiscordError("boom")

    oauth = FailingOAuth()
    svc = PermissionService(oauth=oauth)
    with pytest.raises(DiscordError):
        await asyncio.gather(*[svc.list_my_managed_guilds("AT") for _ in range(3)])
    assert oauth.list_guilds_calls == 1
