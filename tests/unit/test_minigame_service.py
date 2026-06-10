import uuid

import pytest

from app.models.guild import Guild
from app.models.guild_minigame_config import GuildMinigameConfig
from app.repositories.guild import GuildRepository
from app.repositories.minigame_config import MinigameConfigRepository
from app.repositories.user_wallet import WalletRepository
from app.services.minigames import MinigameService

GID = 1212


class _Rng:
    def __init__(self, choices=None, ints=None):
        self._choices = list(choices or [])
        self._ints = list(ints or [])

    def choice(self, seq):
        return self._choices.pop(0)

    def randint(self, a, b):
        return self._ints.pop(0)


async def _setup(db_session, *, enabled=True, min_bet=10, max_bet=10_000, rng=None, balance=1000):
    gid = uuid.uuid4()
    db_session.add(Guild(id=gid, discord_id=GID, name="g", icon_url=None, is_active=True))
    db_session.add(
        GuildMinigameConfig(guild_id=gid, enabled=enabled, min_bet=min_bet, max_bet=max_bet)
    )
    await db_session.commit()
    if balance:
        await WalletRepository(db_session).add_balance(gid, 1, balance)
        await db_session.commit()
    svc = MinigameService(
        guild_repo=GuildRepository(db_session),
        config_repo=MinigameConfigRepository(db_session),
        wallet_repo=WalletRepository(db_session),
        rng=rng,
    )
    return gid, svc


@pytest.mark.asyncio
async def test_coinflip_win_credits_net(db_session):
    gid, svc = await _setup(db_session, rng=_Rng(choices=["heads"]), balance=1000)
    res = await svc.play_coinflip(guild_discord_id=GID, user_id=1, bet=100, choice="heads")
    assert res.won is True
    assert res.payout == 190
    assert res.net == 90
    assert res.balance == 1090


@pytest.mark.asyncio
async def test_coinflip_loss_debits_bet(db_session):
    gid, svc = await _setup(db_session, rng=_Rng(choices=["tails"]), balance=1000)
    res = await svc.play_coinflip(guild_discord_id=GID, user_id=1, bet=100, choice="heads")
    assert res.won is False
    assert res.net == -100
    assert res.balance == 900


@pytest.mark.asyncio
async def test_bet_below_min_rejected(db_session):
    _, svc = await _setup(db_session, min_bet=50, balance=1000)
    with pytest.raises(ValueError):
        await svc.play_coinflip(guild_discord_id=GID, user_id=1, bet=10, choice="heads")


@pytest.mark.asyncio
async def test_bet_above_max_rejected(db_session):
    _, svc = await _setup(db_session, max_bet=500, balance=1000)
    with pytest.raises(ValueError):
        await svc.play_coinflip(guild_discord_id=GID, user_id=1, bet=600, choice="heads")


@pytest.mark.asyncio
async def test_insufficient_funds_rejected(db_session):
    _, svc = await _setup(db_session, balance=50)
    with pytest.raises(ValueError):
        await svc.play_coinflip(guild_discord_id=GID, user_id=1, bet=100, choice="heads")


@pytest.mark.asyncio
async def test_disabled_rejected(db_session):
    _, svc = await _setup(db_session, enabled=False, balance=1000)
    with pytest.raises(ValueError):
        await svc.play_slots(guild_discord_id=GID, user_id=1, bet=100)


@pytest.mark.asyncio
async def test_slots_jackpot(db_session):
    gid, svc = await _setup(db_session, rng=_Rng(choices=["💎", "💎", "💎"]), balance=1000)
    res = await svc.play_slots(guild_discord_id=GID, user_id=1, bet=100)
    assert res.payout == 1000
    assert res.balance == 1900


@pytest.mark.asyncio
async def test_over_under(db_session):
    gid, svc = await _setup(db_session, rng=_Rng(ints=[6, 4, 1]), balance=1000)
    res = await svc.play_over_under(guild_discord_id=GID, user_id=1, bet=100, choice="over")
    assert res.won is True
    assert res.balance == 1090
