import uuid

import pytest

from app.discord_io.errors import DiscordForbidden, DiscordNotFound
from app.models.guild import Guild
from app.repositories.level_role_reward import LevelRoleRewardRepository
from app.services.leveling.level_role_sync import LevelRoleSync
from tests.fakes.discord import FakeDiscordClient


async def _seed(session):
    gid = uuid.uuid4()
    session.add(Guild(id=gid, discord_id=10, name="g", icon_url=None, is_active=True))
    await session.commit()
    return gid


@pytest.mark.asyncio
async def test_replacing_mode_grants_only_highest(db_session):
    gid = await _seed(db_session)
    repo = LevelRoleRewardRepository(db_session)
    await repo.upsert(gid, level=5, role_id=111)
    await repo.upsert(gid, level=10, role_id=222)
    await repo.upsert(gid, level=20, role_id=333)

    fake = FakeDiscordClient()
    sync = LevelRoleSync(reward_repo=repo, discord_io=fake)
    await sync.apply(guild_id=gid, guild_discord_id=10, user_id=42, new_level=12, mode="replacing")

    assert await fake.get_member_role_ids(10, 42) == {222}


@pytest.mark.asyncio
async def test_stacking_mode_grants_all_eligible(db_session):
    gid = await _seed(db_session)
    repo = LevelRoleRewardRepository(db_session)
    await repo.upsert(gid, level=5, role_id=111)
    await repo.upsert(gid, level=10, role_id=222)
    await repo.upsert(gid, level=20, role_id=333)

    fake = FakeDiscordClient()
    sync = LevelRoleSync(reward_repo=repo, discord_io=fake)
    await sync.apply(guild_id=gid, guild_discord_id=10, user_id=42, new_level=15, mode="stacking")

    assert await fake.get_member_role_ids(10, 42) == {111, 222}


@pytest.mark.asyncio
async def test_replacing_mode_removes_old_managed_role(db_session):
    gid = await _seed(db_session)
    repo = LevelRoleRewardRepository(db_session)
    await repo.upsert(gid, level=5, role_id=111)
    await repo.upsert(gid, level=10, role_id=222)

    fake = FakeDiscordClient()
    # Member already has the lv5 role from before they leveled up.
    fake.member_roles[(10, 42)] = {111, 999}  # 999 is unrelated, must stay

    sync = LevelRoleSync(reward_repo=repo, discord_io=fake)
    await sync.apply(guild_id=gid, guild_discord_id=10, user_id=42, new_level=12, mode="replacing")

    roles = await fake.get_member_role_ids(10, 42)
    assert roles == {222, 999}


@pytest.mark.asyncio
async def test_orphan_cleanup_on_role_not_found(db_session):
    gid = await _seed(db_session)
    repo = LevelRoleRewardRepository(db_session)
    await repo.upsert(gid, level=5, role_id=111)

    fake = FakeDiscordClient()
    fake.raise_on_add_role = DiscordNotFound

    sync = LevelRoleSync(reward_repo=repo, discord_io=fake)
    await sync.apply(guild_id=gid, guild_discord_id=10, user_id=42, new_level=5, mode="replacing")

    assert await repo.list_by_guild(gid) == []


@pytest.mark.asyncio
async def test_forbidden_on_add_is_swallowed(db_session, caplog):
    gid = await _seed(db_session)
    repo = LevelRoleRewardRepository(db_session)
    await repo.upsert(gid, level=5, role_id=111)

    fake = FakeDiscordClient()
    fake.raise_on_add_role = DiscordForbidden

    sync = LevelRoleSync(reward_repo=repo, discord_io=fake)
    # Should NOT raise — the level-up flow must continue.
    await sync.apply(guild_id=gid, guild_discord_id=10, user_id=42, new_level=5, mode="replacing")
    # Reward row should NOT be cleaned up — the role still exists, the bot just lacks perms.
    assert len(await repo.list_by_guild(gid)) == 1
