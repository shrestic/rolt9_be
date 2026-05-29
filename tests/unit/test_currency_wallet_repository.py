import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.models.guild import Guild
from app.repositories.user_wallet import WalletRepository


async def _seed_guild(session, gid):
    session.add(Guild(id=gid, discord_id=1, name="g", icon_url=None, is_active=True))
    await session.commit()


@pytest.mark.asyncio
async def test_get_or_create_starts_at_zero(db_session):
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)
    repo = WalletRepository(db_session)
    w = await repo.get_or_create(gid, 42)
    assert w.balance == 0
    assert w.last_daily_at is None


@pytest.mark.asyncio
async def test_add_balance_positive(db_session):
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)
    repo = WalletRepository(db_session)
    ok = await repo.add_balance(gid, 42, 150)
    assert ok is True
    assert (await repo.get(gid, 42)).balance == 150


@pytest.mark.asyncio
async def test_add_balance_negative_within_funds(db_session):
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)
    repo = WalletRepository(db_session)
    await repo.add_balance(gid, 42, 150)
    ok = await repo.add_balance(gid, 42, -100)
    assert ok is True
    assert (await repo.get(gid, 42)).balance == 50


@pytest.mark.asyncio
async def test_add_balance_overdraft_rejected(db_session):
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)
    repo = WalletRepository(db_session)
    await repo.add_balance(gid, 42, 50)
    ok = await repo.add_balance(gid, 42, -100)
    assert ok is False
    assert (await repo.get(gid, 42)).balance == 50


@pytest.mark.asyncio
async def test_set_balance(db_session):
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)
    repo = WalletRepository(db_session)
    await repo.set_balance(gid, 42, 999)
    assert (await repo.get(gid, 42)).balance == 999


@pytest.mark.asyncio
async def test_leaderboard_and_rank(db_session):
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)
    repo = WalletRepository(db_session)
    for uid, bal in [(1, 100), (2, 500), (3, 200)]:
        await repo.set_balance(gid, uid, bal)
    rows, total = await repo.leaderboard(gid, limit=10, offset=0)
    assert total == 3
    assert [r.user_id for r in rows] == [2, 3, 1]
    assert await repo.rank_of(gid, 2) == 1
    assert await repo.rank_of(gid, 1) == 3
    assert await repo.rank_of(gid, 999) is None


@pytest.mark.asyncio
async def test_try_claim_daily_first_time(db_session):
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)
    repo = WalletRepository(db_session)
    now = datetime(2026, 5, 29, 12, 0, tzinfo=UTC)
    cutoff = now - timedelta(hours=24)
    ok = await repo.try_claim_daily(
        gid, 42, amount=100, now=now, cutoff=cutoff, new_streak=1, new_longest=1
    )
    assert ok is True
    w = await repo.get(gid, 42)
    assert w.balance == 100
    assert w.last_daily_at is not None


@pytest.mark.asyncio
async def test_try_claim_daily_blocks_second_claim_same_now(db_session):
    # Two claims at the same `now` simulate a concurrent double-fire: the
    # cooldown guard in the UPDATE must let only the first through.
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)
    repo = WalletRepository(db_session)
    now = datetime(2026, 5, 29, 12, 0, tzinfo=UTC)
    cutoff = now - timedelta(hours=24)
    first = await repo.try_claim_daily(
        gid, 42, amount=100, now=now, cutoff=cutoff, new_streak=1, new_longest=1
    )
    second = await repo.try_claim_daily(
        gid, 42, amount=100, now=now, cutoff=cutoff, new_streak=2, new_longest=2
    )
    assert first is True
    assert second is False
    assert (await repo.get(gid, 42)).balance == 100  # not doubled


@pytest.mark.asyncio
async def test_try_claim_daily_allows_after_24h(db_session):
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)
    repo = WalletRepository(db_session)
    day1 = datetime(2026, 5, 29, 12, 0, tzinfo=UTC)
    await repo.try_claim_daily(
        gid,
        42,
        amount=100,
        now=day1,
        cutoff=day1 - timedelta(hours=24),
        new_streak=1,
        new_longest=1,
    )
    day2 = day1 + timedelta(hours=25)
    ok = await repo.try_claim_daily(
        gid,
        42,
        amount=100,
        now=day2,
        cutoff=day2 - timedelta(hours=24),
        new_streak=2,
        new_longest=2,
    )
    assert ok is True
    assert (await repo.get(gid, 42)).balance == 200


@pytest.mark.asyncio
async def test_claim_daily_sets_streak_counters(db_session):
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)
    repo = WalletRepository(db_session)
    now = datetime(2026, 5, 29, 12, 0, tzinfo=UTC)
    cutoff = now - timedelta(hours=24)
    ok = await repo.try_claim_daily(
        gid, 42, amount=100, now=now, cutoff=cutoff, new_streak=1, new_longest=1
    )
    assert ok is True
    w = await repo.get(gid, 42)
    assert w.current_streak == 1
    assert w.longest_streak == 1


@pytest.mark.asyncio
async def test_claim_daily_double_fire_does_not_double_streak(db_session):
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)
    repo = WalletRepository(db_session)
    now = datetime(2026, 5, 29, 12, 0, tzinfo=UTC)
    cutoff = now - timedelta(hours=24)
    first = await repo.try_claim_daily(
        gid, 42, amount=100, now=now, cutoff=cutoff, new_streak=1, new_longest=1
    )
    second = await repo.try_claim_daily(
        gid, 42, amount=100, now=now, cutoff=cutoff, new_streak=2, new_longest=2
    )
    assert first is True
    assert second is False
    w = await repo.get(gid, 42)
    assert w.current_streak == 1  # the rejected second claim left it alone
    assert w.balance == 100


@pytest.mark.asyncio
async def test_claim_daily_longest_preserved_on_reset(db_session):
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)
    repo = WalletRepository(db_session)
    day1 = datetime(2026, 5, 29, 12, 0, tzinfo=UTC)
    await repo.try_claim_daily(
        gid,
        42,
        amount=100,
        now=day1,
        cutoff=day1 - timedelta(hours=24),
        new_streak=5,
        new_longest=5,
    )
    day2 = day1 + timedelta(hours=49)  # window broken → caller resets streak to 1
    await repo.try_claim_daily(
        gid,
        42,
        amount=100,
        now=day2,
        cutoff=day2 - timedelta(hours=24),
        new_streak=1,
        new_longest=5,
    )
    w = await repo.get(gid, 42)
    assert w.current_streak == 1
    assert w.longest_streak == 5  # record kept
