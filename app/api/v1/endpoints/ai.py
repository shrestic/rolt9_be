"""HTTP endpoints for AI settings + monthly usage readout.

Mounted under `/api/v1/guilds/{guild_id}/ai/...`, gated by `require_managed_guild`.
GET/PUT return settings plus the current UTC month's token usage so the dashboard
can show "X / Y tokens used". UoW: repo flushes, request boundary commits.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends

from app.dependencies.guild import require_managed_guild
from app.dependencies.services import (
    get_ai_config_repository,
    get_ai_usage_repository,
)
from app.models.guild import Guild
from app.repositories.ai_config import AIConfigRepository
from app.repositories.ai_usage import AIUsageRepository
from app.schemas.ai import AISettings, AISettingsOut
from app.services.ai.ai_gateway import month_key

router = APIRouter()


async def _out(cfg, guild_id, usage_repo: AIUsageRepository) -> AISettingsOut:
    used = await usage_repo.tokens_this_period(guild_id, month_key(datetime.now(UTC)))
    return AISettingsOut(
        enabled=cfg.enabled,
        monthly_token_budget=cfg.monthly_token_budget,
        tokens_used_this_month=used,
    )


@router.get("/{guild_id}/ai/settings", response_model=AISettingsOut)
async def get_settings(
    guild: Guild = Depends(require_managed_guild),
    repo: AIConfigRepository = Depends(get_ai_config_repository),
    usage_repo: AIUsageRepository = Depends(get_ai_usage_repository),
):
    cfg = await repo.get_or_create(guild.id)
    return await _out(cfg, guild.id, usage_repo)


@router.put("/{guild_id}/ai/settings", response_model=AISettingsOut)
async def update_settings(
    payload: AISettings,
    guild: Guild = Depends(require_managed_guild),
    repo: AIConfigRepository = Depends(get_ai_config_repository),
    usage_repo: AIUsageRepository = Depends(get_ai_usage_repository),
):
    cfg = await repo.upsert(guild.id, payload.model_dump())
    return await _out(cfg, guild.id, usage_repo)
