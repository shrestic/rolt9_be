"""HTTP endpoints for karma: per-guild settings + read-only leaderboard.

Mounted under `/api/v1/guilds/{guild_id}/karma/...`, gated by
`require_managed_guild`. Settings use the config repo; the leaderboard uses the
karma repo directly. User IDs go out as strings (snowflake precision). UoW: repo
flushes, request boundary commits.
"""

from fastapi import APIRouter, Depends, Query

from app.dependencies.guild import require_managed_guild
from app.dependencies.services import (
    get_karma_config_repository,
    get_karma_repository,
)
from app.models.guild import Guild
from app.repositories.karma import KarmaRepository
from app.repositories.karma_config import KarmaConfigRepository
from app.schemas.karma import (
    KarmaLeaderboardEntryOut,
    KarmaLeaderboardPageOut,
    KarmaSettings,
)

router = APIRouter()


@router.get("/{guild_id}/karma/settings", response_model=KarmaSettings)
async def get_settings(
    guild: Guild = Depends(require_managed_guild),
    repo: KarmaConfigRepository = Depends(get_karma_config_repository),
):
    """Return the current karma settings for the guild (defaults if never set)."""
    cfg = await repo.get_or_create(guild.id)
    return KarmaSettings(enabled=cfg.enabled)


@router.put("/{guild_id}/karma/settings", response_model=KarmaSettings)
async def update_settings(
    payload: KarmaSettings,
    guild: Guild = Depends(require_managed_guild),
    repo: KarmaConfigRepository = Depends(get_karma_config_repository),
):
    """Overwrite karma settings for the guild; creates defaults first if needed."""
    cfg = await repo.upsert(guild.id, payload.model_dump())
    return KarmaSettings(enabled=cfg.enabled)


@router.get("/{guild_id}/karma/leaderboard", response_model=KarmaLeaderboardPageOut)
async def get_leaderboard(
    guild: Guild = Depends(require_managed_guild),
    page: int = Query(default=1, ge=1, le=10_000),
    page_size: int = Query(default=20, ge=1, le=100),
    repo: KarmaRepository = Depends(get_karma_repository),
):
    """Return one page of the karma leaderboard sorted by points descending."""
    rows, total = await repo.leaderboard(guild.id, limit=page_size, offset=(page - 1) * page_size)
    items = [
        KarmaLeaderboardEntryOut(
            # rank is absolute (not reset to 1 on each page) so page 2 starts at page_size+1
            rank=(page - 1) * page_size + i + 1,
            user_id=str(r.user_id),
            points=r.points,
        )
        for i, r in enumerate(rows)
    ]
    return KarmaLeaderboardPageOut(items=items, total=total, page=page, page_size=page_size)
