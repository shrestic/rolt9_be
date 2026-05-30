"""HTTP endpoints for mini-games settings.

Mounted under `/api/v1/guilds/{guild_id}/minigame/...`, gated by
`require_managed_guild`. Settings only (bet bounds + enable); the games run in
the bot. UoW: repo flushes, request boundary commits.
"""

from fastapi import APIRouter, Depends

from app.dependencies.guild import require_managed_guild
from app.dependencies.services import get_minigame_config_repository
from app.models.guild import Guild
from app.repositories.minigame_config import MinigameConfigRepository
from app.schemas.minigame import MinigameSettings

router = APIRouter()


def _out(cfg) -> MinigameSettings:
    return MinigameSettings(enabled=cfg.enabled, min_bet=cfg.min_bet, max_bet=cfg.max_bet)


@router.get("/{guild_id}/minigame/settings", response_model=MinigameSettings)
async def get_settings(
    guild: Guild = Depends(require_managed_guild),
    repo: MinigameConfigRepository = Depends(get_minigame_config_repository),
):
    return _out(await repo.get_or_create(guild.id))


@router.put("/{guild_id}/minigame/settings", response_model=MinigameSettings)
async def update_settings(
    payload: MinigameSettings,
    guild: Guild = Depends(require_managed_guild),
    repo: MinigameConfigRepository = Depends(get_minigame_config_repository),
):
    return _out(await repo.upsert(guild.id, payload.model_dump()))
