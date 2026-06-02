import uuid
from datetime import UTC, datetime

import pytest

from app.models.guild import Guild
from app.models.guild_wc_config import DEFAULT_SHAME_PREFIX, GuildWCConfig
from app.models.wc_match import WCMatch
from app.models.wc_prediction import WCPrediction


@pytest.mark.asyncio
async def test_wc_models_crud(db_session):
    gid = uuid.uuid4()
    db_session.add(Guild(id=gid, discord_id=1, name="g", icon_url=None, is_active=True))
    m = WCMatch(
        id=1001,
        competition="WC",
        home_team="Brazil",
        home_code="BR",
        away_team="Argentina",
        away_code="AR",
        kickoff_at=datetime(2026, 6, 20, 12, tzinfo=UTC),
        status="scheduled",
        ou_line=2.5,
        handicap_team="home",
        handicap_line=0.5,
    )
    db_session.add(m)
    db_session.add(GuildWCConfig(guild_id=gid))
    await db_session.commit()
    db_session.add(
        WCPrediction(
            guild_id=gid,
            match_id=1001,
            user_discord_id=42,
            bet_type="1x2",
            pick="home",
        )
    )
    await db_session.commit()
    cfg = await db_session.get(GuildWCConfig, gid)
    assert cfg.enabled is False and cfg.shame_nick_prefix == DEFAULT_SHAME_PREFIX
