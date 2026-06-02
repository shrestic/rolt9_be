import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.models.guild import Guild
from app.repositories.wc_config import WCConfigRepository
from app.repositories.wc_match import WCMatchRepository
from app.repositories.wc_prediction import WCPredictionRepository


async def _guild(s):
    gid = uuid.uuid4()
    s.add(Guild(id=gid, discord_id=1, name="g", icon_url=None, is_active=True))
    await s.commit()
    return gid


@pytest.mark.asyncio
async def test_match_upsert_and_due_to_settle(db_session):
    repo = WCMatchRepository(db_session)
    now = datetime.now(UTC)
    await repo.upsert(
        {
            "id": 1,
            "home_team": "BRA",
            "home_code": "BR",
            "away_team": "ARG",
            "away_code": "AR",
            "kickoff_at": now - timedelta(hours=3),
            "status": "finished",
            "home_score": 2,
            "away_score": 1,
            "ou_line": 2.5,
            "handicap_team": "home",
            "handicap_line": 0.5,
        }
    )
    await repo.upsert(
        {  # cập nhật lại cùng id -> không tạo trùng
            "id": 1,
            "home_team": "BRA",
            "home_code": "BR",
            "away_team": "ARG",
            "away_code": "AR",
            "kickoff_at": now - timedelta(hours=3),
            "status": "finished",
            "home_score": 3,
            "away_score": 1,
            "ou_line": 2.5,
        }
    )
    await db_session.commit()
    finished = await repo.finished_unsettled()
    assert len(finished) == 1 and finished[0].home_score == 3
    await repo.mark_settled(1)
    await db_session.commit()
    assert await repo.finished_unsettled() == []


@pytest.mark.asyncio
async def test_prediction_upsert_replaces_same_key(db_session):
    gid = await _guild(db_session)
    mrepo = WCMatchRepository(db_session)
    await mrepo.upsert(
        {
            "id": 5,
            "home_team": "A",
            "away_team": "B",
            "kickoff_at": datetime.now(UTC),
            "status": "scheduled",
        }
    )
    await db_session.commit()
    prepo = WCPredictionRepository(db_session)
    await prepo.upsert(gid, 5, 42, "1x2", "home")
    await prepo.upsert(gid, 5, 42, "1x2", "away")  # cùng key -> đổi pick, không tạo mới
    await db_session.commit()
    mine = await prepo.for_user_match(gid, 5, 42)
    assert len(mine) == 1 and mine[0].pick == "away"


@pytest.mark.asyncio
async def test_config_get_or_create(db_session):
    gid = await _guild(db_session)
    repo = WCConfigRepository(db_session)
    cfg = await repo.get_or_create(gid)
    assert cfg.enabled is False
    await repo.upsert(gid, {"enabled": True, "channel_id": 99})
    await db_session.commit()
    assert (await repo.get(gid)).channel_id == 99
