from types import SimpleNamespace

import pytest

from app.bot.events import handle_guild_join, handle_guild_remove
from app.repositories.guild import GuildRepository
from app.repositories.guild_settings import GuildSettingsRepository


@pytest.mark.asyncio
async def test_handle_guild_join_inserts_guild_and_settings(db_session):
    fake_guild = SimpleNamespace(
        id=12345,
        name="X",
        icon=SimpleNamespace(url="http://i/x.png"),
    )

    await handle_guild_join(fake_guild, db_session)

    g = await GuildRepository(db_session).get_by_discord_id(12345)
    assert g is not None
    assert g.is_active is True
    s = await GuildSettingsRepository(db_session).get(g.id)
    assert s is not None


@pytest.mark.asyncio
async def test_handle_guild_remove_marks_inactive(db_session):
    fake_guild = SimpleNamespace(id=12345, name="X", icon=None)
    await handle_guild_join(fake_guild, db_session)
    await handle_guild_remove(fake_guild, db_session)
    g = await GuildRepository(db_session).get_by_discord_id(12345)
    assert g.is_active is False  # type: ignore
