"""HTTP endpoints for badges: per-guild enable toggle + read-only catalog.

Mounted under `/api/v1/guilds/{guild_id}/badges/...`, gated by
`require_managed_guild`. The catalog is static (from code), so its endpoint
just serialises `BADGES`; settings use the config repo (Unit-of-Work commit at
the boundary).
"""

from fastapi import APIRouter, Depends

from app.dependencies.guild import require_managed_guild
from app.dependencies.services import get_badge_config_repository
from app.models.guild import Guild
from app.repositories.badge_config import BadgeConfigRepository
from app.schemas.badges import BadgeCatalogEntry, BadgeSettings
from app.services.badges.catalog import BADGES

router = APIRouter()


@router.get("/{guild_id}/badges/settings", response_model=BadgeSettings)
async def get_settings(
    guild: Guild = Depends(require_managed_guild),
    repo: BadgeConfigRepository = Depends(get_badge_config_repository),
):
    """Return the current badge config for the guild (defaults if never set)."""
    cfg = await repo.get_or_create(guild.id)
    return BadgeSettings(enabled=cfg.enabled)


@router.put("/{guild_id}/badges/settings", response_model=BadgeSettings)
async def update_settings(
    payload: BadgeSettings,
    guild: Guild = Depends(require_managed_guild),
    repo: BadgeConfigRepository = Depends(get_badge_config_repository),
):
    """Toggle badges on or off for the guild and persist the change."""
    cfg = await repo.upsert(guild.id, payload.model_dump())
    return BadgeSettings(enabled=cfg.enabled)


@router.get("/{guild_id}/badges/catalog", response_model=list[BadgeCatalogEntry])
async def get_catalog(
    guild: Guild = Depends(require_managed_guild),
):
    """Return the full static badge catalog so the dashboard can render it.

    The catalog is the same for every guild; the guild gate is just to ensure
    only managers of *this* guild can see (and later configure) the list.
    """
    return [
        BadgeCatalogEntry(
            key=b.key,
            name=b.name,
            emoji=b.emoji,
            description=b.description,
            stat=b.stat,
            threshold=b.threshold,
        )
        for b in BADGES
    ]
