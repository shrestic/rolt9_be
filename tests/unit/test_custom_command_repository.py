import pytest

from app.exceptions.http_exceptions import ConflictError
from app.repositories.custom_command import CustomCommandRepository
from app.repositories.guild import GuildRepository


async def _make_guild(db_session, discord_id=1):
    return await GuildRepository(db_session).upsert(discord_id=discord_id, name="g", icon_url=None)


@pytest.mark.asyncio
async def test_create_lowercases_trigger(db_session):
    g = await _make_guild(db_session)
    repo = CustomCommandRepository(db_session)
    c = await repo.create(
        guild_id=g.id, data={"trigger": "Rules", "response_type": "text", "response_text": "hi"}
    )
    assert c.trigger == "rules"


@pytest.mark.asyncio
async def test_duplicate_trigger_raises_conflict(db_session):
    g = await _make_guild(db_session)
    repo = CustomCommandRepository(db_session)
    await repo.create(
        guild_id=g.id, data={"trigger": "rules", "response_type": "text", "response_text": "a"}
    )
    with pytest.raises(ConflictError):
        await repo.create(
            guild_id=g.id, data={"trigger": "RULES", "response_type": "text", "response_text": "b"}
        )


@pytest.mark.asyncio
async def test_list_by_guild_and_enabled_only(db_session):
    g = await _make_guild(db_session)
    repo = CustomCommandRepository(db_session)
    await repo.create(
        guild_id=g.id, data={"trigger": "a", "response_type": "text", "response_text": "x"}
    )
    disabled = await repo.create(
        guild_id=g.id, data={"trigger": "b", "response_type": "text", "response_text": "y"}
    )
    await repo.update(guild_id=g.id, command_id=disabled.id, data={"enabled": False})
    assert len(await repo.list_by_guild(g.id)) == 2
    assert len(await repo.list_by_guild(g.id, enabled_only=True)) == 1


@pytest.mark.asyncio
async def test_update_and_delete(db_session):
    g = await _make_guild(db_session)
    repo = CustomCommandRepository(db_session)
    c = await repo.create(
        guild_id=g.id, data={"trigger": "a", "response_type": "text", "response_text": "x"}
    )
    updated = await repo.update(guild_id=g.id, command_id=c.id, data={"response_text": "z"})
    assert updated.response_text == "z"
    assert await repo.delete(guild_id=g.id, command_id=c.id) is True
    assert await repo.get(guild_id=g.id, command_id=c.id) is None
    assert await repo.delete(guild_id=g.id, command_id=c.id) is False
