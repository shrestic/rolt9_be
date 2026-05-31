"""HTTP endpoints cho AI settings (BYO-key v2) + usage token/USD + catalog.

Mounted dưới `/api/v1/guilds/{guild_id}/ai/...`, gate `require_managed_guild`.
GET/PUT KHÔNG BAO GIỜ trả key thật — chỉ `has_key` + `key_hint` (4 ký tự cuối).
`api_key` trong PUT ghi-một-chiều: None=giữ, ""=xóa, "sk-..."=đặt mới.
Catalog (`/ai/catalog`, không cần guild_id) feed dropdown cho FE.
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
# Router riêng cho catalog (không có guild_id) — mount với prefix "/ai" ở api.py.
catalog_router = APIRouter()


def _kb_out(e) -> KbEntryOut:
    return KbEntryOut(id=str(e.id), title=e.title, content=e.content)


def _key_hint(api_key_enc: bytes | None) -> str:
    """4 ký tự cuối của key (để admin nhận ra key nào), "" nếu chưa có/giải mã lỗi."""
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
    # Validate provider/model qua catalog khi có chọn (cho phép để trống = chưa cấu hình).
    if (payload.provider or payload.model) and not is_valid(payload.provider, payload.model):
        raise HTTPException(status_code=422, detail="Provider/model không hỗ trợ.")
    # Build dict cập nhật, loại api_key ra (xử lý riêng vì ghi-một-chiều).
    data = payload.model_dump(exclude={"api_key"})
    if payload.api_key is not None:
        # "" => xóa key (NULL); chuỗi khác => mã hóa & lưu.
        data["api_key_enc"] = encrypt_str(payload.api_key) if payload.api_key else None
    cfg = await repo.upsert(guild.id, data)
    return await _out(cfg, guild.id, usage_repo)


@catalog_router.get("/catalog")
async def get_catalog():
    """Whitelist provider/model cho FE (không cần guild_id, không cần gate guild)."""
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
