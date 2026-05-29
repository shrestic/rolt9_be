import uuid

import pytest

from app.models.guild import Guild
from app.models.guild_currency_config import GuildCurrencyConfig
from app.models.user_wallet import UserWallet


async def _seed_guild(session, gid):
    session.add(Guild(id=gid, discord_id=1, name="g", icon_url=None, is_active=True))
    await session.commit()


def test_config_has_expected_columns():
    cols = GuildCurrencyConfig.__table__.columns
    for name in (
        "enabled",
        "currency_name",
        "currency_emoji",
        "earn_min",
        "earn_max",
        "daily_amount",
        "allow_pay",
    ):
        assert name in cols


def test_wallet_has_expected_columns():
    cols = UserWallet.__table__.columns
    for name in ("guild_id", "user_id", "balance", "last_daily_at"):
        assert name in cols


@pytest.mark.asyncio
async def test_can_insert_wallet_and_config(db_session):
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)
    db_session.add(GuildCurrencyConfig(guild_id=gid))
    db_session.add(UserWallet(guild_id=gid, user_id=42, balance=0))
    await db_session.commit()
    assert True
