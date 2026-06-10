import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.models.guild import Guild
from app.models.guild_currency_config import GuildCurrencyConfig
from app.repositories.currency_config import CurrencyConfigRepository
from app.repositories.guild import GuildRepository
from app.repositories.user_wallet import WalletRepository
from app.services.currency import CurrencyService

GUILD_DISCORD_ID = 555


async def _seed(session, *, enabled=True, earn_min=2, earn_max=2, daily=100, allow_pay=True):
    gid = uuid.uuid4()
    session.add(Guild(id=gid, discord_id=GUILD_DISCORD_ID, name="g", icon_url=None, is_active=True))
    await session.commit()
    await CurrencyConfigRepository(session).upsert(
        gid,
        {
            "enabled": enabled,
            "earn_min": earn_min,
            "earn_max": earn_max,
            "daily_amount": daily,
            "allow_pay": allow_pay,
        },
    )
    return gid


def _service(session) -> CurrencyService:
    return CurrencyService(
        session=session,
        guild_repo=GuildRepository(session),
        config_repo=CurrencyConfigRepository(session),
        wallet_repo=WalletRepository(session),
    )


@pytest.mark.asyncio
async def test_grant_message_reward_adds_in_range(db_session):
    await _seed(db_session, earn_min=2, earn_max=2)
    svc = _service(db_session)
    amount = await svc.grant_message_reward(guild_discord_id=GUILD_DISCORD_ID, user_id=7)
    assert amount == 2
    assert await svc.get_balance(guild_discord_id=GUILD_DISCORD_ID, user_id=7) == 2


@pytest.mark.asyncio
async def test_grant_skipped_when_disabled(db_session):
    await _seed(db_session, enabled=False)
    svc = _service(db_session)
    amount = await svc.grant_message_reward(guild_discord_id=GUILD_DISCORD_ID, user_id=7)
    assert amount is None
    assert await svc.get_balance(guild_discord_id=GUILD_DISCORD_ID, user_id=7) == 0


@pytest.mark.asyncio
async def test_claim_daily_then_cooldown(db_session):
    await _seed(db_session, daily=100)
    svc = _service(db_session)
    now = datetime(2026, 5, 29, 12, 0, tzinfo=UTC)
    first = await svc.claim_daily(guild_discord_id=GUILD_DISCORD_ID, user_id=7, now=now)
    assert first.claimed is True
    # streak_enabled=True by default, per_day=10, so day-1 bonus=10 → total=110
    assert first.amount == 110
    assert first.balance == 110
    second = await svc.claim_daily(
        guild_discord_id=GUILD_DISCORD_ID, user_id=7, now=now + timedelta(hours=1)
    )
    assert second.claimed is False
    assert second.retry_after_seconds > 0


@pytest.mark.asyncio
async def test_pay_transfers(db_session):
    await _seed(db_session, allow_pay=True)
    svc = _service(db_session)
    await svc.admin_set(guild_discord_id=GUILD_DISCORD_ID, user_id=1, value=300)
    new_sender = await svc.pay(
        guild_discord_id=GUILD_DISCORD_ID, sender_id=1, receiver_id=2, amount=120
    )
    assert new_sender == 180
    assert await svc.get_balance(guild_discord_id=GUILD_DISCORD_ID, user_id=2) == 120


@pytest.mark.asyncio
async def test_pay_insufficient_funds(db_session):
    await _seed(db_session)
    svc = _service(db_session)
    await svc.admin_set(guild_discord_id=GUILD_DISCORD_ID, user_id=1, value=50)
    with pytest.raises(ValueError):
        await svc.pay(guild_discord_id=GUILD_DISCORD_ID, sender_id=1, receiver_id=2, amount=80)
    assert await svc.get_balance(guild_discord_id=GUILD_DISCORD_ID, user_id=1) == 50
    assert await svc.get_balance(guild_discord_id=GUILD_DISCORD_ID, user_id=2) == 0


@pytest.mark.asyncio
async def test_pay_rejects_self_and_bad_amount(db_session):
    await _seed(db_session)
    svc = _service(db_session)
    await svc.admin_set(guild_discord_id=GUILD_DISCORD_ID, user_id=1, value=500)
    with pytest.raises(ValueError):
        await svc.pay(guild_discord_id=GUILD_DISCORD_ID, sender_id=1, receiver_id=1, amount=10)
    with pytest.raises(ValueError):
        await svc.pay(guild_discord_id=GUILD_DISCORD_ID, sender_id=1, receiver_id=2, amount=0)
    with pytest.raises(ValueError):
        await svc.pay(
            guild_discord_id=GUILD_DISCORD_ID, sender_id=1, receiver_id=2, amount=2_000_000
        )


@pytest.mark.asyncio
async def test_pay_disabled_when_allow_pay_false(db_session):
    await _seed(db_session, allow_pay=False)
    svc = _service(db_session)
    await svc.admin_set(guild_discord_id=GUILD_DISCORD_ID, user_id=1, value=500)
    with pytest.raises(ValueError):
        await svc.pay(guild_discord_id=GUILD_DISCORD_ID, sender_id=1, receiver_id=2, amount=10)


@pytest.mark.asyncio
async def test_admin_add_and_take(db_session):
    await _seed(db_session)
    svc = _service(db_session)
    assert await svc.admin_add(guild_discord_id=GUILD_DISCORD_ID, user_id=1, delta=500) == 500
    assert await svc.admin_add(guild_discord_id=GUILD_DISCORD_ID, user_id=1, delta=-200) == 300
    with pytest.raises(ValueError):
        await svc.admin_add(guild_discord_id=GUILD_DISCORD_ID, user_id=1, delta=-9999)


@pytest.mark.asyncio
async def test_unknown_guild_raises(db_session):
    svc = _service(db_session)
    with pytest.raises(LookupError):
        await svc.claim_daily(guild_discord_id=99999, user_id=1, now=datetime.now(UTC))


# ---------------------------------------------------------------------------
# Streak tests — use a separate guild (discord_id=777) and a dedicated _setup
# helper so these don't collide with the GUILD_DISCORD_ID=555 fixtures above.
# ---------------------------------------------------------------------------


async def _setup(db_session, **cfg_overrides):
    """Seed a guild + currency config (discord_id=777) and return a CurrencyService.

    Any keyword arg in cfg_overrides is forwarded to GuildCurrencyConfig so
    tests can pin streak settings (streak_bonus_per_day, streak_bonus_cap, etc.)
    without going through the upsert dict path.
    """
    gid = uuid.uuid4()
    db_session.add(Guild(id=gid, discord_id=777, name="g", icon_url=None, is_active=True))
    cfg = GuildCurrencyConfig(guild_id=gid, enabled=True, daily_amount=100, **cfg_overrides)
    db_session.add(cfg)
    await db_session.commit()
    return CurrencyService(
        session=db_session,
        guild_repo=GuildRepository(db_session),
        config_repo=CurrencyConfigRepository(db_session),
        wallet_repo=WalletRepository(db_session),
    )


@pytest.mark.asyncio
async def test_first_daily_starts_streak_one_no_bonus(db_session):
    svc = await _setup(db_session, streak_bonus_per_day=10, streak_bonus_cap=500)
    res = await svc.claim_daily(guild_discord_id=777, user_id=1)
    assert res.claimed is True
    assert res.streak == 1
    assert res.base == 100
    assert res.streak_bonus == 10  # 1 * 10
    assert res.amount == 110


@pytest.mark.asyncio
async def test_consecutive_daily_increments_and_bonuses(db_session):
    svc = await _setup(db_session, streak_bonus_per_day=10, streak_bonus_cap=500)
    d1 = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    await svc.claim_daily(guild_discord_id=777, user_id=1, now=d1)
    d2 = d1 + timedelta(hours=25)
    res = await svc.claim_daily(guild_discord_id=777, user_id=1, now=d2)
    assert res.streak == 2
    assert res.streak_bonus == 20
    assert res.amount == 120


@pytest.mark.asyncio
async def test_milestone_day_adds_lump(db_session):
    # Walk a 7-day chain; day 7 should carry the +200 milestone.
    svc = await _setup(db_session, streak_bonus_per_day=10, streak_bonus_cap=500)
    start = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    res = None
    for i in range(7):
        res = await svc.claim_daily(
            guild_discord_id=777, user_id=1, now=start + timedelta(hours=25 * i)
        )
    assert res.streak == 7
    assert res.milestone_bonus == 200
    assert res.amount == 100 + 70 + 200  # base + 7*10 + milestone


@pytest.mark.asyncio
async def test_daily_resets_on_calendar_day_not_24h(db_session):
    # The whole point of the day-based reset: claiming late one day (23:00) and
    # again early the NEXT day (01:00) is allowed even though only ~2h elapsed —
    # because it's a new UTC day — and the streak continues.
    svc = await _setup(db_session, streak_bonus_per_day=10, streak_bonus_cap=500)
    late = datetime(2026, 5, 1, 23, 0, tzinfo=UTC)
    first = await svc.claim_daily(guild_discord_id=777, user_id=1, now=late)
    assert first.claimed is True
    assert first.streak == 1

    next_day_early = datetime(2026, 5, 2, 1, 0, tzinfo=UTC)  # only 2h later
    second = await svc.claim_daily(guild_discord_id=777, user_id=1, now=next_day_early)
    assert second.claimed is True, "a new UTC day must allow a fresh claim within 24h"
    assert second.streak == 2, "consecutive calendar days continue the chain"


@pytest.mark.asyncio
async def test_second_claim_same_day_blocked_after_many_hours(db_session):
    # Conversely, two claims on the SAME UTC day are blocked even 10h apart.
    svc = await _setup(db_session, streak_bonus_per_day=10, streak_bonus_cap=500)
    morning = datetime(2026, 5, 1, 8, 0, tzinfo=UTC)
    await svc.claim_daily(guild_discord_id=777, user_id=1, now=morning)
    evening = datetime(2026, 5, 1, 18, 0, tzinfo=UTC)  # same day, 10h later
    second = await svc.claim_daily(guild_discord_id=777, user_id=1, now=evening)
    assert second.claimed is False
    # retry_after points at the next UTC midnight (6h away), not "24h from claim".
    assert 0 < second.retry_after_seconds <= 6 * 3600


@pytest.mark.asyncio
async def test_streak_disabled_only_base(db_session):
    svc = await _setup(db_session, streak_enabled=False)
    res = await svc.claim_daily(guild_discord_id=777, user_id=1)
    assert res.amount == 100
    assert res.streak == 0
    assert res.streak_bonus == 0
    assert res.milestone_bonus == 0


@pytest.mark.asyncio
async def test_get_streak_reports_current_and_longest(db_session):
    svc = await _setup(db_session, streak_bonus_per_day=10, streak_bonus_cap=500)
    d1 = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    await svc.claim_daily(guild_discord_id=777, user_id=1, now=d1)
    await svc.claim_daily(guild_discord_id=777, user_id=1, now=d1 + timedelta(hours=25))
    info = await svc.get_streak(guild_discord_id=777, user_id=1)
    assert info.current == 2
    assert info.longest == 2
    assert info.days_to_milestone == 5  # 7 - 2
    assert info.enabled is True


@pytest.mark.asyncio
async def test_reenable_streak_restarts_from_one(db_session):
    """Regression: disabling streak while active should drop the chain to 0 so
    that re-enabling starts fresh at 1 (spec decision #6: "re-enable -> count from the start")
    rather than resuming the frozen count.

    Steps:
    1. Build a streak-enabled guild and claim twice → current_streak == 2.
    2. Disable streak, claim again → base only, current_streak persisted as 0.
    3. Re-enable, claim again → streak restarts at 1 (not 3/4), longest preserved.
    """
    # --- Step 1: claim twice, build a chain of 2 ---
    svc = await _setup(db_session, streak_bonus_per_day=10, streak_bonus_cap=500)
    d1 = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    d2 = d1 + timedelta(hours=25)
    d3 = d2 + timedelta(hours=25)
    d4 = d3 + timedelta(hours=25)

    await svc.claim_daily(guild_discord_id=777, user_id=1, now=d1)
    res_d2 = await svc.claim_daily(guild_discord_id=777, user_id=1, now=d2)
    assert res_d2.streak == 2, "setup: should have streak=2 after two consecutive claims"

    # --- Step 2: disable streak, claim at d3 → base only, chain dropped to 0 ---
    # Fetch the guild's internal UUID so we can call the config repo directly.
    guild = await GuildRepository(db_session).get_by_discord_id(777)
    cfg_repo = CurrencyConfigRepository(db_session)
    await cfg_repo.upsert(guild.id, {"streak_enabled": False})
    await db_session.commit()

    res_d3 = await svc.claim_daily(guild_discord_id=777, user_id=1, now=d3)
    assert res_d3.claimed is True
    assert res_d3.amount == 100, "disabled streak: should only grant base amount"
    assert res_d3.streak_bonus == 0
    # The service should have written new_streak=0 to the wallet.
    # We verify via get_streak, which reads the stored wallet value.
    info_after_disable = await svc.get_streak(guild_discord_id=777, user_id=1)
    assert (
        info_after_disable.current == 0
    ), "after disabling, chain should be 0 (not frozen at old value)"

    # --- Step 3: re-enable, claim at d4 → restarts at 1, longest still 2 ---
    await cfg_repo.upsert(guild.id, {"streak_enabled": True})
    await db_session.commit()

    res_d4 = await svc.claim_daily(guild_discord_id=777, user_id=1, now=d4)
    assert res_d4.claimed is True
    assert (
        res_d4.streak == 1
    ), "re-enabled streak must restart at 1, not resume from the old frozen count"
    # longest_streak is preserved by the max() even though new_streak=1
    info_final = await svc.get_streak(guild_discord_id=777, user_id=1)
    assert info_final.longest == 2, "all-time record (2) must survive the reset"
