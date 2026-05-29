import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.models.guild import Guild
from app.models.guild_leveling_config import GuildLevelingConfig
from app.models.guild_rank_card_theme import GuildRankCardTheme
from app.repositories.guild import GuildRepository
from app.repositories.guild_rank_card_theme import GuildRankCardThemeRepository
from app.repositories.level_role_reward import LevelRoleRewardRepository
from app.repositories.leveling_config import GuildLevelingConfigRepository
from app.repositories.user_xp import UserXpRepository
from app.services.leveling.leveling_service import LevelingService
from tests.fakes.discord import FakeDiscordClient


async def _seed(session, *, enabled=True, mode="channel", channel_id=100):
    gid = uuid.uuid4()
    session.add(Guild(id=gid, discord_id=10, name="g", icon_url=None, is_active=True))
    session.add(
        GuildLevelingConfig(
            guild_id=gid,
            enabled=enabled,
            notification_mode=mode,
            notification_channel_id=channel_id,
        )
    )
    session.add(GuildRankCardTheme(guild_id=gid))
    await session.commit()
    return gid


def _build_service(session, fake):
    return LevelingService(
        session=session,
        discord_io=fake,
        guild_repo=GuildRepository(session),
        config_repo=GuildLevelingConfigRepository(session),
        xp_repo=UserXpRepository(session),
        reward_repo=LevelRoleRewardRepository(session),
        theme_repo=GuildRankCardThemeRepository(session),
    )


@pytest.mark.asyncio
async def test_process_message_awards_xp_when_enabled(db_session, monkeypatch):
    await _seed(db_session)
    fake = FakeDiscordClient()
    svc = _build_service(db_session, fake)
    monkeypatch.setattr("random.randint", lambda a, b: 25)

    out = await svc.process_message(
        guild_discord_id=10, user_id=42, username="alice", content="hello there"
    )
    assert out is not None
    assert out.amount == 25


@pytest.mark.asyncio
async def test_process_message_skipped_when_disabled(db_session):
    await _seed(db_session, enabled=False)
    fake = FakeDiscordClient()
    svc = _build_service(db_session, fake)

    out = await svc.process_message(
        guild_discord_id=10, user_id=42, username="alice", content="hello there"
    )
    assert out is None


@pytest.mark.asyncio
async def test_process_message_filtered_by_content(db_session):
    await _seed(db_session)
    fake = FakeDiscordClient()
    svc = _build_service(db_session, fake)

    out = await svc.process_message(guild_discord_id=10, user_id=42, username="alice", content="hi")
    assert out is None  # too short


@pytest.mark.asyncio
async def test_process_message_triggers_level_up_notification(db_session, monkeypatch):
    gid = await _seed(db_session, mode="channel", channel_id=100)
    fake = FakeDiscordClient()
    svc = _build_service(db_session, fake)
    repo = UserXpRepository(db_session)
    await repo.get_or_create(gid, user_id=42)
    await repo.set_xp(
        gid, user_id=42, total_xp=99, last_xp_at=datetime.now(UTC) - timedelta(seconds=120)
    )
    monkeypatch.setattr("random.randint", lambda a, b: 20)

    out = await svc.process_message(
        guild_discord_id=10, user_id=42, username="alice", content="hello there"
    )
    assert out is not None
    assert out.new_level == 1
    assert any(ch == 100 for ch, _, _ in fake.posted_messages)


@pytest.mark.asyncio
async def test_get_rank_returns_data(db_session):
    gid = await _seed(db_session)
    repo = UserXpRepository(db_session)
    await repo.get_or_create(gid, user_id=42)
    await repo.set_xp(gid, user_id=42, total_xp=250)

    fake = FakeDiscordClient()
    svc = _build_service(db_session, fake)
    rank = await svc.get_rank(guild_discord_id=10, user_id=42)
    assert rank is not None
    assert rank.total_xp == 250
    assert rank.level == 1
    assert rank.rank == 1


@pytest.mark.asyncio
async def test_get_rank_for_unknown_user_returns_zero_row(db_session):
    await _seed(db_session)
    fake = FakeDiscordClient()
    svc = _build_service(db_session, fake)
    rank = await svc.get_rank(guild_discord_id=10, user_id=999)
    assert rank is not None
    assert rank.total_xp == 0
    assert rank.level == 0


@pytest.mark.asyncio
async def test_set_member_xp_strips_role_when_xp_lowered(db_session):
    gid = await _seed(db_session)
    # Configure rewards: level 5 → role 555, level 10 → role 999
    from app.repositories.level_role_reward import LevelRoleRewardRepository

    rewards = LevelRoleRewardRepository(db_session)
    await rewards.upsert(gid, level=5, role_id=555)
    await rewards.upsert(gid, level=10, role_id=999)
    # Member currently has role 999 (from a previous level-10 award)
    fake = FakeDiscordClient()
    fake.member_roles[(10, 42)] = {999, 12345}  # 12345 is unrelated, must stay
    svc = _build_service(db_session, fake)

    # Admin sets XP to 100 (level 1 — neither reward applies)
    info = await svc.set_member_xp(guild_discord_id=10, user_id=42, total_xp=100)
    assert info is not None
    assert info.level == 1
    # Both managed roles should be gone; unrelated role stays.
    assert await fake.get_member_role_ids(10, 42) == {12345}


@pytest.mark.asyncio
async def test_set_member_xp_grants_role_when_xp_raised(db_session):
    gid = await _seed(db_session)
    from app.repositories.level_role_reward import LevelRoleRewardRepository

    rewards = LevelRoleRewardRepository(db_session)
    await rewards.upsert(gid, level=5, role_id=555)
    fake = FakeDiscordClient()
    svc = _build_service(db_session, fake)

    # Admin sets XP to 5000 (well past level 5)
    info = await svc.set_member_xp(guild_discord_id=10, user_id=42, total_xp=5000)
    assert info is not None
    assert info.level >= 5
    # Member should now have role 555.
    assert 555 in await fake.get_member_role_ids(10, 42)


@pytest.mark.asyncio
async def test_reset_member_strips_all_level_roles(db_session):
    gid = await _seed(db_session)
    from app.repositories.level_role_reward import LevelRoleRewardRepository

    rewards = LevelRoleRewardRepository(db_session)
    await rewards.upsert(gid, level=5, role_id=555)
    await rewards.upsert(gid, level=10, role_id=999)
    # Member has both level roles + an unrelated role
    fake = FakeDiscordClient()
    fake.member_roles[(10, 42)] = {555, 999, 12345}
    repo = UserXpRepository(db_session)
    await repo.get_or_create(gid, user_id=42)
    await repo.set_xp(gid, user_id=42, total_xp=5000)
    svc = _build_service(db_session, fake)

    info = await svc.reset_member(guild_discord_id=10, user_id=42)
    assert info is not None
    assert info.total_xp == 0
    assert info.level == 0
    # All managed roles stripped; unrelated role 12345 stays.
    assert await fake.get_member_role_ids(10, 42) == {12345}


@pytest.mark.asyncio
async def test_reset_member_when_no_config(db_session):
    # Guild without leveling config — reset should still wipe XP gracefully.
    import uuid

    from app.models.guild import Guild

    gid = uuid.uuid4()
    db_session.add(Guild(id=gid, discord_id=20, name="g2", icon_url=None, is_active=True))
    await db_session.commit()
    repo = UserXpRepository(db_session)
    await repo.get_or_create(gid, user_id=99)
    await repo.set_xp(gid, user_id=99, total_xp=500)

    fake = FakeDiscordClient()
    svc = _build_service(db_session, fake)
    info = await svc.reset_member(guild_discord_id=20, user_id=99)
    assert info is not None
    assert info.total_xp == 0
