import pytest

from app.bot.events import handle_guild_join, handle_guild_remove, handle_ready
from app.discord_io.types import GuildInfo
from app.repositories.guild import GuildRepository
from app.repositories.guild_settings import GuildSettingsRepository


@pytest.mark.asyncio
async def test_handle_guild_join_inserts_guild_and_settings(db_session):
    info = GuildInfo(discord_id=12345, name="X", icon_url="http://i/x.png")
    await handle_guild_join(info, db_session)

    g = await GuildRepository(db_session).get_by_discord_id(12345)
    assert g is not None
    assert g.is_active is True
    s = await GuildSettingsRepository(db_session).get(g.id)
    assert s is not None


@pytest.mark.asyncio
async def test_handle_guild_remove_marks_inactive(db_session):
    info = GuildInfo(discord_id=12345, name="X", icon_url=None)
    await handle_guild_join(info, db_session)
    await handle_guild_remove(info, db_session)
    g = await GuildRepository(db_session).get_by_discord_id(12345)
    assert g.is_active is False  # type: ignore


@pytest.mark.asyncio
async def test_handle_ready_backfills_connected_guilds(db_session):
    guilds = [
        GuildInfo(discord_id=111, name="A", icon_url="http://i/a.png"),
        GuildInfo(discord_id=222, name="B", icon_url=None),
    ]

    await handle_ready(guilds, db_session)

    repo = GuildRepository(db_session)
    a = await repo.get_by_discord_id(111)
    b = await repo.get_by_discord_id(222)
    assert a is not None and a.is_active is True
    assert b is not None and b.is_active is True


@pytest.mark.asyncio
async def test_handle_ready_reactivates_previously_removed_guild(db_session):
    info = GuildInfo(discord_id=333, name="C", icon_url=None)
    await handle_guild_join(info, db_session)
    await handle_guild_remove(info, db_session)

    await handle_ready([info], db_session)

    g = await GuildRepository(db_session).get_by_discord_id(333)
    assert g is not None and g.is_active is True  # type: ignore
