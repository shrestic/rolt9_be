"""HTTP endpoints for AI settings (BYO-key v2) + token/USD usage + catalog.

Mounted under `/api/v1/guilds/{guild_id}/ai/...`, gated by `require_managed_guild`.
GET/PUT NEVER return the real key — only `has_key` + `key_hint` (last 4 characters).
`api_key` in PUT is write-only: None=keep, ""=clear, "sk-..."=set new.
Catalog (`/ai/catalog`, no guild_id needed) feeds the FE dropdown.
UoW: repo flush, request boundary commit.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Path

from app.core.crypto import decrypt_str, encrypt_str
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
from app.services.ai.catalog import AI_CATALOG, is_valid

router = APIRouter()
# Separate router for the catalog (no guild_id) — mounted with prefix "/ai" in api.py.
catalog_router = APIRouter()


def _kb_out(e) -> KbEntryOut:
    return KbEntryOut(id=str(e.id), title=e.title, content=e.content)


def _key_hint(api_key_enc: bytes | None) -> str:
    """Last 4 characters of the key (so the admin can tell which key it is), "" if none/decrypt fails."""
    if api_key_enc is None:
        return ""
    try:
        return decrypt_str(api_key_enc)[-4:]
    except Exception:  # noqa: BLE001
        return ""


async def _out(cfg, guild_id, usage_repo: AIUsageRepository) -> AISettingsOut:
    pk = month_key(datetime.now(UTC))
    return AISettingsOut(
        enabled=cfg.enabled,
        provider=cfg.provider,
        model=cfg.model,
        monthly_budget_usd=cfg.monthly_budget_usd,
        persona=cfg.persona,
        agent_enabled=cfg.agent_enabled,
        agent_channel_id=(str(cfg.agent_channel_id) if cfg.agent_channel_id is not None else None),
        tools_enabled=cfg.tools_enabled,
        actions_enabled=cfg.actions_enabled,
        companion_enabled=cfg.companion_enabled,
        companion_channel_id=(
            str(cfg.companion_channel_id) if cfg.companion_channel_id is not None else None
        ),
        companion_cooldown_min=cfg.companion_cooldown_min,
        has_key=cfg.api_key_enc is not None,
        key_hint=_key_hint(cfg.api_key_enc),
        tokens_used_this_month=await usage_repo.tokens_this_period(guild_id, pk),
        cost_used_this_month=await usage_repo.cost_this_period(guild_id, pk),
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
    # Validate provider/model via the catalog when one is chosen (allow empty = not configured yet).
    if (payload.provider or payload.model) and not is_valid(payload.provider, payload.model):
        raise HTTPException(status_code=422, detail="Provider/model not supported.")
    # Build the update dict, leaving out api_key (handled separately since it's write-only).
    data = payload.model_dump(exclude={"api_key"})
    # Snowflake string → int (or None) at the DB boundary.
    data["agent_channel_id"] = int(payload.agent_channel_id) if payload.agent_channel_id else None
    data["companion_channel_id"] = (
        int(payload.companion_channel_id) if payload.companion_channel_id else None
    )
    if payload.api_key is not None:
        # "" => clear key (NULL); any other string => encrypt & store.
        data["api_key_enc"] = encrypt_str(payload.api_key) if payload.api_key else None
    cfg = await repo.upsert(guild.id, data)
    return await _out(cfg, guild.id, usage_repo)


@catalog_router.get("/catalog")
async def get_catalog():
    """Whitelisted provider/model for the FE (no guild_id needed, no guild gate needed)."""
    return AI_CATALOG


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
