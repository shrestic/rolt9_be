import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.models.guild import Guild
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
    assert first.amount == 100
    assert first.balance == 100
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
