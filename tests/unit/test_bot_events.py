import pytest

from app.bot.events import (
    handle_guild_join,
    handle_guild_remove,
    handle_guild_update,
    handle_ready,
)
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
async def test_handle_guild_update_refreshes_name_and_icon(db_session):
    await handle_guild_join(
        GuildInfo(discord_id=12345, name="Old Name", icon_url="http://i/old.png"),
        db_session,
    )
    await handle_guild_update(
        GuildInfo(discord_id=12345, name="New Name", icon_url="http://i/new.png"),
        db_session,
    )
    g = await GuildRepository(db_session).get_by_discord_id(12345)
    assert g is not None
    assert g.name == "New Name"
    assert g.icon_url == "http://i/new.png"


@pytest.mark.asyncio
async def test_handle_guild_update_does_not_create_settings_row(db_session):
    # Idempotency: updating a guild we don't yet have should still upsert it
    # (Discord can dispatch an update event before our join handler runs for
    # transient connection cases). The handler must NOT create a settings row —
    # only join does that — but the guilds row must appear.
    await handle_guild_update(
        GuildInfo(discord_id=99999, name="Renamed", icon_url=None), db_session
    )
    g = await GuildRepository(db_session).get_by_discord_id(99999)
    assert g is not None and g.name == "Renamed"
    s = await GuildSettingsRepository(db_session).get(g.id)
    assert s is None


@pytest.mark.asyncio
async def test_handle_ready_reactivates_previously_removed_guild(db_session):
    info = GuildInfo(discord_id=333, name="C", icon_url=None)
    await handle_guild_join(info, db_session)
    await handle_guild_remove(info, db_session)

    await handle_ready([info], db_session)

    g = await GuildRepository(db_session).get_by_discord_id(333)
    assert g is not None and g.is_active is True  # type: ignore
