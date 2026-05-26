import pytest

from app.repositories.guild import GuildRepository
from app.repositories.mod_case import ModCaseRepository


async def _make_guild(db_session, discord_id=1):
    return await GuildRepository(db_session).upsert(discord_id=discord_id, name="g", icon_url=None)


@pytest.fixture
def case_kwargs():
    return {
        "action": "ban",
        "source": "manual",
        "target_user_id": 500,
        "target_username": "bad#1",
        "moderator_user_id": 600,
        "moderator_username": "mod#1",
        "reason": "spam",
    }


@pytest.mark.asyncio
async def test_case_number_starts_at_one_and_increments(db_session, case_kwargs):
    g = await _make_guild(db_session)
    repo = ModCaseRepository(db_session)
    c1 = await repo.create_case(guild_id=g.id, **case_kwargs)
    c2 = await repo.create_case(guild_id=g.id, **case_kwargs)
    assert c1.case_number == 1
    assert c2.case_number == 2


@pytest.mark.asyncio
async def test_case_number_is_per_guild(db_session, case_kwargs):
    g1 = await _make_guild(db_session, 1)
    g2 = await _make_guild(db_session, 2)
    repo = ModCaseRepository(db_session)
    await repo.create_case(guild_id=g1.id, **case_kwargs)
    other = await repo.create_case(guild_id=g2.id, **case_kwargs)
    assert other.case_number == 1


@pytest.mark.asyncio
async def test_active_warn_count_only_counts_active_warns(db_session):
    g = await _make_guild(db_session)
    repo = ModCaseRepository(db_session)
    base = {
        "source": "manual",
        "target_user_id": 500,
        "target_username": "t",
        "moderator_user_id": 600,
        "moderator_username": "m",
        "reason": None,
    }
    w1 = await repo.create_case(guild_id=g.id, action="warn", **base)
    await repo.create_case(guild_id=g.id, action="warn", **base)
    await repo.create_case(guild_id=g.id, action="ban", **base)  # not a warn
    assert await repo.active_warn_count(g.id, 500) == 2
    await repo.deactivate(w1)
    assert await repo.active_warn_count(g.id, 500) == 1


@pytest.mark.asyncio
async def test_list_cases_filters_and_paginates(db_session):
    g = await _make_guild(db_session)
    repo = ModCaseRepository(db_session)
    base = {
        "source": "manual",
        "target_username": "t",
        "moderator_user_id": 600,
        "moderator_username": "m",
        "reason": None,
    }
    await repo.create_case(guild_id=g.id, action="warn", target_user_id=1, **base)
    await repo.create_case(guild_id=g.id, action="ban", target_user_id=1, **base)
    await repo.create_case(guild_id=g.id, action="warn", target_user_id=2, **base)
    items, total = await repo.list_cases(guild_id=g.id, action="warn")
    assert total == 2
    assert {c.action for c in items} == {"warn"}
    items2, total2 = await repo.list_cases(guild_id=g.id, target_user_id=2)
    assert total2 == 1
    assert items2[0].target_user_id == 2


@pytest.mark.asyncio
async def test_get_by_case_number(db_session, case_kwargs):
    g = await _make_guild(db_session)
    repo = ModCaseRepository(db_session)
    created = await repo.create_case(guild_id=g.id, **case_kwargs)
    found = await repo.get_by_case_number(g.id, created.case_number)
    assert found is not None and found.id == created.id
    assert await repo.get_by_case_number(g.id, 999) is None
