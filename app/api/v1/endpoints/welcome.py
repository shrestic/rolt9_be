"""HTTP endpoints for the Welcome plugin settings.

Mounted under `/api/v1/guilds/{guild_id}/welcome/...`, gated by
`require_managed_guild`. `channel_id` is a string on the wire (snowflake) and
coerced to int for storage. UoW: repo flushes, request boundary commits.
"""

from fastapi import APIRouter, Depends

from app.dependencies.guild import require_managed_guild
from app.dependencies.services import get_welcome_config_repository
from app.models.guild import Guild
from app.repositories.welcome_config import WelcomeConfigRepository
from app.schemas.welcome import WelcomeSettings

router = APIRouter()


def _out(cfg) -> WelcomeSettings:
    return WelcomeSettings(
        enabled=cfg.enabled,
        channel_id=str(cfg.channel_id) if cfg.channel_id is not None else None,
        welcome_template=cfg.welcome_template,
        ai_welcome=cfg.ai_welcome,
        leave_enabled=cfg.leave_enabled,
        leave_template=cfg.leave_template,
    )


@router.get("/{guild_id}/welcome/settings", response_model=WelcomeSettings)
async def get_settings(
    guild: Guild = Depends(require_managed_guild),
    repo: WelcomeConfigRepository = Depends(get_welcome_config_repository),
):
    return _out(await repo.get_or_create(guild.id))


@router.put("/{guild_id}/welcome/settings", response_model=WelcomeSettings)
async def update_settings(
    payload: WelcomeSettings,
    guild: Guild = Depends(require_managed_guild),
    repo: WelcomeConfigRepository = Depends(get_welcome_config_repository),
):
    data = payload.model_dump()
    # Snowflake string → int (or None) at the DB boundary.
    data["channel_id"] = int(payload.channel_id) if payload.channel_id else None
    return _out(await repo.upsert(guild.id, data))
