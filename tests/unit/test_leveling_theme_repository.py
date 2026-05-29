import uuid

import pytest

from app.models.guild import Guild
from app.repositories.guild_rank_card_theme import GuildRankCardThemeRepository


async def _seed(session):
    gid = uuid.uuid4()
    session.add(Guild(id=gid, discord_id=1, name="g", icon_url=None, is_active=True))
    await session.commit()
    return gid


@pytest.mark.asyncio
async def test_get_or_create_returns_defaults(db_session):
    gid = await _seed(db_session)
    repo = GuildRankCardThemeRepository(db_session)
    t = await repo.get_or_create(gid)
    assert t.bg_type == "gradient"
    assert t.bg_color_1 == "#0f172a"


@pytest.mark.asyncio
async def test_upsert_updates_fields(db_session):
    gid = await _seed(db_session)
    repo = GuildRankCardThemeRepository(db_session)
    await repo.get_or_create(gid)
    updated = await repo.upsert(
        gid, {"bg_type": "solid", "bg_color_1": "#ff00ff", "accent_color": "#000000"}
    )
    assert updated.bg_type == "solid"
    assert updated.bg_color_1 == "#ff00ff"
    assert updated.accent_color == "#000000"
