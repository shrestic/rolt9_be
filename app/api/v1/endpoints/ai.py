"""HTTP endpoints for AI settings + monthly usage readout.

Mounted under `/api/v1/guilds/{guild_id}/ai/...`, gated by `require_managed_guild`.
GET/PUT return settings plus the current UTC month's token usage so the dashboard
can show "X / Y tokens used". UoW: repo flushes, request boundary commits.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Path

from app.dependencies.guild import require_managed_guild
from app.dependencies.services import (
    get_ai_config_repository,
    get_ai_usage_repository,
    get_kb_repository,
)
from app.models.guild import Guild
from app.repositories.ai_config import AIConfigRepository
from app.repositories.ai_usage import AIUsageRepository
from app.repositories.kb import KbRepository
from app.schemas.ai import AISettings, AISettingsOut, KbEntryIn, KbEntryOut
from app.services.ai.ai_gateway import month_key

router = APIRouter()


def _kb_out(e) -> KbEntryOut:
    return KbEntryOut(id=str(e.id), title=e.title, content=e.content)


async def _out(cfg, guild_id, usage_repo: AIUsageRepository) -> AISettingsOut:
    used = await usage_repo.tokens_this_period(guild_id, month_key(datetime.now(UTC)))
    return AISettingsOut(
        enabled=cfg.enabled,
        monthly_token_budget=cfg.monthly_token_budget,
        persona=cfg.persona,
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


@router.get("/{guild_id}/ai/kb", response_model=list[KbEntryOut])
async def list_kb(
    guild: Guild = Depends(require_managed_guild),
    repo: KbRepository = Depends(get_kb_repository),
):
    return [_kb_out(e) for e in await repo.list_for_guild(guild.id)]


@router.post("/{guild_id}/ai/kb", response_model=KbEntryOut)
async def create_kb(
    payload: KbEntryIn,
    guild: Guild = Depends(require_managed_guild),
    repo: KbRepository = Depends(get_kb_repository),
):
    return _kb_out(await repo.create(guild.id, title=payload.title, content=payload.content))


@router.delete("/{guild_id}/ai/kb/{entry_id}")
async def delete_kb(
    entry_id: uuid.UUID = Path(...),
    guild: Guild = Depends(require_managed_guild),
    repo: KbRepository = Depends(get_kb_repository),
):
    entry = await repo.get(guild.id, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="KB entry not found")
    await repo.delete(entry)
    return {"ok": True}
