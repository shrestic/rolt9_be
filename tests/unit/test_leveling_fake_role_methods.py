import pytest

from app.discord_io.errors import DiscordForbidden, DiscordNotFound
from tests.fakes.discord import FakeDiscordClient


@pytest.mark.asyncio
async def test_add_role_records_membership():
    fake = FakeDiscordClient()
    await fake.add_role(guild_id=1, user_id=2, role_id=3)
    assert (1, 2, 3) in fake.role_grants
    assert 3 in await fake.get_member_role_ids(1, 2)


@pytest.mark.asyncio
async def test_remove_role_undoes_add():
    fake = FakeDiscordClient()
    await fake.add_role(1, 2, 3)
    await fake.remove_role(1, 2, 3)
    assert 3 not in await fake.get_member_role_ids(1, 2)


@pytest.mark.asyncio
async def test_get_member_role_ids_returns_empty_for_unknown():
    fake = FakeDiscordClient()
    assert await fake.get_member_role_ids(1, 2) == set()


@pytest.mark.asyncio
async def test_raise_on_add_role_simulates_forbidden():
    fake = FakeDiscordClient()
    fake.raise_on_add_role = DiscordForbidden
    with pytest.raises(DiscordForbidden):
        await fake.add_role(1, 2, 3)


@pytest.mark.asyncio
async def test_raise_on_add_role_can_simulate_not_found():
    fake = FakeDiscordClient()
    fake.raise_on_add_role = DiscordNotFound
    with pytest.raises(DiscordNotFound):
        await fake.add_role(1, 2, 3)
