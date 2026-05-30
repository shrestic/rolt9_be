"""HTTP endpoints for the server pet: per-guild settings + read-only status.

Mounted under `/api/v1/guilds/{guild_id}/pet/...`, gated by `require_managed_guild`.
Settings use the pet repo (get_or_create / upsert_config); status is computed
through PetService (which settles decay) and never mutates. Unit-of-Work: repo
flushes, request boundary commits.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies.guild import require_managed_guild
from app.dependencies.services import (
    get_pet_cooldown_repository,
    get_pet_repository,
)
from app.models.guild import Guild
from app.repositories.guild import GuildRepository
from app.repositories.pet import PetRepository
from app.repositories.pet_cooldown import PetCooldownRepository
from app.repositories.user_wallet import WalletRepository
from app.schemas.pet import PetSettings, PetStatusOut
from app.services.pet import PetService

router = APIRouter()


def _settings_out(pet) -> PetSettings:
    """Map a GuildPet ORM row to the wire schema.

    Single serialisation point — both GET and PUT return the same shape,
    so a misalignment between model and schema surfaces in tests immediately.
    """
    return PetSettings(
        enabled=pet.enabled,
        name=pet.name,
        feed_cost=pet.feed_cost,
        feed_amount=pet.feed_amount,
        play_amount=pet.play_amount,
        decay_per_day=pet.decay_per_day,
    )


@router.get("/{guild_id}/pet/settings", response_model=PetSettings)
async def get_settings(
    guild: Guild = Depends(require_managed_guild),
    repo: PetRepository = Depends(get_pet_repository),
):
    """Return the guild's pet configuration.

    Uses `get_or_create` so an unconfigured guild gets sane defaults rather
    than a 404 — the dashboard always has something to render.
    """
    return _settings_out(await repo.get_or_create(guild.id))


@router.put("/{guild_id}/pet/settings", response_model=PetSettings)
async def update_settings(
    payload: PetSettings,
    guild: Guild = Depends(require_managed_guild),
    repo: PetRepository = Depends(get_pet_repository),
):
    """Persist a full settings update; creates the row first if needed.

    Validation (name not empty, amounts ≥ 1, etc.) happens inside PetSettings
    before the handler runs, so the repo only sees a clean payload.
    """
    return _settings_out(await repo.upsert_config(guild.id, payload.model_dump()))


@router.get("/{guild_id}/pet/status", response_model=PetStatusOut)
async def get_status(
    guild: Guild = Depends(require_managed_guild),
    repo: PetRepository = Depends(get_pet_repository),
    cooldown_repo: PetCooldownRepository = Depends(get_pet_cooldown_repository),
):
    """Return the pet's settled read-only status (hunger, happiness, level, stage).

    Delegates to PetService.get_status(), which applies lazy decay so the
    returned stats reflect elapsed time without a background job. This endpoint
    is read-only — decay is computed but NOT persisted (no save_state call).

    404 is only returned when the guild row itself is missing; a guild without a
    pet row returns a disabled sentinel (enabled=False, hunger=100, happiness=100).
    """
    service = PetService(
        guild_repo=GuildRepository(repo.session),
        pet_repo=repo,
        cooldown_repo=cooldown_repo,
        wallet_repo=WalletRepository(repo.session),
    )
    status = await service.get_status(guild_discord_id=guild.discord_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Pet not found")
    return PetStatusOut(
        name=status.name,
        hunger=status.hunger,
        happiness=status.happiness,
        xp=status.xp,
        level=status.level,
        stage_name=status.stage_name,
        stage_emoji=status.stage_emoji,
        mood_emoji=status.mood_emoji,
        enabled=status.enabled,
    )
