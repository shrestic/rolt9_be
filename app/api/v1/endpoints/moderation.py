# Moderation endpoints for the dashboard:
#   GET   /{guild_id}/moderation             → read the guild's moderation settings
#   PUT   /{guild_id}/moderation             → update settings
#                                              (mod_log_channel, dm_on_action, escalation rules)
#   GET   /{guild_id}/cases                  → list cases (filter + paginate)
#   GET   /{guild_id}/cases/{case_number}    → details for one case
#   DELETE /{guild_id}/cases/{case_number}   → deactivate the case +
#                                              revoke the Discord ban if it's a ban case
#
# Every endpoint uses require_managed_guild → auth + permission + bot-present check.

from fastapi import APIRouter, Depends, Query

from app.dependencies.guild import require_managed_guild
from app.dependencies.services import (
    get_guild_settings_repository,
    get_mod_case_repository,
    get_moderation_service,
)
from app.discord_io.errors import DiscordError
from app.exceptions.http_exceptions import BadRequestError, NotFoundError
from app.models.guild import Guild
from app.models.mod_case import ModCase
from app.repositories.guild_settings import GuildSettingsRepository
from app.repositories.mod_case import ModCaseRepository
from app.schemas.moderation import CasesPage, ModCaseOut, ModerationSettings
from app.services.moderation.service import ModerationService

router = APIRouter()


# Convert an ORM ModCase → the response DTO ModCaseOut. Large Discord IDs are
# stringified because JS numbers lose precision past 2^53; the FE would corrupt
# them otherwise.
def _case_out(c: ModCase) -> ModCaseOut:
    return ModCaseOut(
        case_number=c.case_number,
        action=c.action,
        source=c.source,
        target_user_id=str(c.target_user_id),
        target_username=c.target_username,
        moderator_user_id=str(c.moderator_user_id),
        moderator_username=c.moderator_username,
        reason=c.reason,
        duration_seconds=c.duration_seconds,
        created_at=c.created_at,
        active=c.active,
    )


@router.get("/{guild_id}/moderation", response_model=ModerationSettings)
async def get_moderation_settings(
    guild: Guild = Depends(require_managed_guild),
    settings_repo: GuildSettingsRepository = Depends(get_guild_settings_repository),
):
    gs = await settings_repo.get(guild.id)
    return ModerationSettings(**((gs.moderation if gs else {}) or {}))


@router.put("/{guild_id}/moderation", response_model=ModerationSettings)
async def update_moderation_settings(
    payload: ModerationSettings,
    guild: Guild = Depends(require_managed_guild),
    settings_repo: GuildSettingsRepository = Depends(get_guild_settings_repository),
):
    # update_section overwrites the entire `moderation` JSON with `payload`.
    gs = await settings_repo.update_section(guild.id, "moderation", payload.model_dump())
    return ModerationSettings(**gs.moderation)


@router.get("/{guild_id}/cases", response_model=CasesPage)
async def list_cases(
    guild: Guild = Depends(require_managed_guild),
    target_user_id: str | None = Query(default=None),
    action: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    cases: ModCaseRepository = Depends(get_mod_case_repository),
):
    target = int(target_user_id) if target_user_id else None
    items, total = await cases.list_cases(
        guild_id=guild.id,
        target_user_id=target,
        action=action,
        skip=(page - 1) * page_size,
        limit=page_size,
    )
    return CasesPage(
        items=[_case_out(c) for c in items], total=total, page=page, page_size=page_size
    )


@router.get("/{guild_id}/cases/{case_number}", response_model=ModCaseOut)
async def get_case(
    case_number: int,
    guild: Guild = Depends(require_managed_guild),
    cases: ModCaseRepository = Depends(get_mod_case_repository),
):
    c = await cases.get_by_case_number(guild.id, case_number)
    if c is None:
        raise NotFoundError(detail="Case not found")
    return _case_out(c)


# DELETE = "close the case" (soft-delete via active=False) + revoke the Discord
# ban if the case is a ban.
# Flow:
#   1. Look up the case by (guild_id, case_number). 404 if not found.
#   2. Call ModerationService.deactivate_case — the service decides on its own
#      to revoke on Discord if action == "ban", then marks active=False.
#   3. If the Discord revoke fails (e.g. the bot lost permission) → 400 UNBAN_FAILED.
@router.delete("/{guild_id}/cases/{case_number}", response_model=ModCaseOut)
async def deactivate_case(
    case_number: int,
    guild: Guild = Depends(require_managed_guild),
    cases: ModCaseRepository = Depends(get_mod_case_repository),
    moderation: ModerationService = Depends(get_moderation_service),
):
    c = await cases.get_by_case_number(guild.id, case_number)
    if c is None:
        raise NotFoundError(detail="Case not found")
    try:
        await moderation.deactivate_case(guild_id=guild.discord_id, case=c)
    except DiscordError as exc:
        # The 4 exception classes are the only Discord-side failures every
        # adapter raises. The endpoint only needs to catch DiscordError (base)
        # — it never sees discord.* or httpx.*. The error_code is generic
        # ("revoke") because deactivate can reverse either a ban or a mute.
        raise BadRequestError(
            detail="Could not revoke the Discord action (the bot may lack permission).",
            error_code="REVOKE_FAILED",
        ) from exc
    return _case_out(c)
