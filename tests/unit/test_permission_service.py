import pytest
import respx
from httpx import Response

from app.services.permission_service import PermissionService

GUILDS_URL = "https://discord.com/api/users/@me/guilds"


@pytest.mark.asyncio
@respx.mock
async def test_can_manage_owner_returns_true():
    respx.get(GUILDS_URL).mock(
        return_value=Response(
            200,
            json=[
                {"id": "1", "name": "A", "icon": None, "owner": True, "permissions": "0"},
            ],
        )
    )
    svc = PermissionService()
    assert await svc.user_can_manage(access_token="AT", guild_id_str="1") is True


@pytest.mark.asyncio
@respx.mock
async def test_can_manage_manage_guild_bit_returns_true():
    respx.get(GUILDS_URL).mock(
        return_value=Response(
            200,
            json=[
                {"id": "2", "name": "B", "icon": None, "owner": False, "permissions": "32"},
            ],
        )
    )
    svc = PermissionService()
    assert await svc.user_can_manage(access_token="AT", guild_id_str="2") is True


@pytest.mark.asyncio
@respx.mock
async def test_can_manage_administrator_returns_true():
    respx.get(GUILDS_URL).mock(
        return_value=Response(
            200,
            json=[
                {"id": "3", "name": "C", "icon": None, "owner": False, "permissions": "8"},
            ],
        )
    )
    svc = PermissionService()
    assert await svc.user_can_manage(access_token="AT", guild_id_str="3") is True


@pytest.mark.asyncio
@respx.mock
async def test_can_manage_member_returns_false():
    respx.get(GUILDS_URL).mock(
        return_value=Response(
            200,
            json=[
                {"id": "4", "name": "D", "icon": None, "owner": False, "permissions": "0"},
            ],
        )
    )
    svc = PermissionService()
    assert await svc.user_can_manage(access_token="AT", guild_id_str="4") is False


@pytest.mark.asyncio
@respx.mock
async def test_list_my_guilds_filters_to_managed_only():
    respx.get(GUILDS_URL).mock(
        return_value=Response(
            200,
            json=[
                {"id": "1", "name": "A", "icon": None, "owner": True, "permissions": "0"},
                {"id": "2", "name": "B", "icon": None, "owner": False, "permissions": "0"},
                {"id": "3", "name": "C", "icon": None, "owner": False, "permissions": "32"},
            ],
        )
    )
    svc = PermissionService()
    ids = [g.discord_id for g in await svc.list_my_managed_guilds(access_token="AT")]
    assert sorted(ids) == [1, 3]


@pytest.mark.asyncio
@respx.mock
async def test_cache_hits_dont_hit_discord_twice():
    route = respx.get(GUILDS_URL).mock(
        return_value=Response(
            200,
            json=[
                {"id": "1", "name": "A", "icon": None, "owner": True, "permissions": "0"},
            ],
        )
    )
    svc = PermissionService()
    await svc.list_my_managed_guilds(access_token="AT")
    await svc.list_my_managed_guilds(access_token="AT")
    assert route.call_count == 1
