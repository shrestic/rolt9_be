"""HTTP endpoints for the server-currency feature.

Mounted under `/api/v1/guilds/{guild_id}/currency/...`, gated by
`require_managed_guild` (dashboard auth + `manage_guild` + bot-in-guild).
The dependency injects a `Guild` ORM row, so handlers use the internal UUID
directly.

Snowflakes (user IDs) are **strings on the wire** in both directions. JSON
numbers lose precision past 2^53, so client code treats them as opaque
strings. We coerce to int at the database boundary and stringify on the way
back out.

Transaction model: every handler runs inside `get_db`'s `async with` block.
The session commits when the handler returns and rolls back on any exception;
repos in this module only `flush()` — they never commit on their own
(Unit-of-Work, commit at the boundary — see `app/db/session.py`).
"""

from fastapi import APIRouter, Depends, Path, Query

from app.dependencies.guild import require_managed_guild
from app.dependencies.services import (
    get_currency_config_repository,
    get_wallet_repository,
)
from app.models.guild import Guild
from app.repositories.currency_config import CurrencyConfigRepository
from app.repositories.user_wallet import WalletRepository
from app.schemas.currency import (
    CurrencySettings,
    WalletBalanceUpdate,
    WalletLeaderboardEntryOut,
    WalletLeaderboardPageOut,
    WalletMemberOut,
)

router = APIRouter()


def _settings_out(cfg) -> CurrencySettings:
    """Map a `GuildCurrencyConfig` ORM row to the wire schema.

    A single place so both the GET and PUT handlers serialise identically.
    """
    return CurrencySettings(
        enabled=cfg.enabled,
        currency_name=cfg.currency_name,
        currency_emoji=cfg.currency_emoji,
        earn_min=cfg.earn_min,
        earn_max=cfg.earn_max,
        daily_amount=cfg.daily_amount,
        allow_pay=cfg.allow_pay,
        streak_enabled=cfg.streak_enabled,
        streak_bonus_per_day=cfg.streak_bonus_per_day,
        streak_bonus_cap=cfg.streak_bonus_cap,
    )


@router.get("/{guild_id}/currency/settings", response_model=CurrencySettings)
async def get_settings(
    guild: Guild = Depends(require_managed_guild),
    repo: CurrencyConfigRepository = Depends(get_currency_config_repository),
):
    """Return the guild's currency settings.

    Uses `get_or_create`, so an unconfigured guild gets sane defaults instead
    of a 404 — the dashboard always has a row to render.
    """
    return _settings_out(await repo.get_or_create(guild.id))


@router.put("/{guild_id}/currency/settings", response_model=CurrencySettings)
async def update_settings(
    payload: CurrencySettings,
    guild: Guild = Depends(require_managed_guild),
    repo: CurrencyConfigRepository = Depends(get_currency_config_repository),
):
    """Persist a full settings update; creates the row first if needed.

    Validation (caps, earn_min ≤ earn_max) happens in `CurrencySettings` before
    the handler runs, so the repo only sees a sane payload.
    """
    cfg = await repo.upsert(guild.id, payload.model_dump())
    return _settings_out(cfg)


@router.get("/{guild_id}/currency/leaderboard", response_model=WalletLeaderboardPageOut)
async def get_leaderboard(
    guild: Guild = Depends(require_managed_guild),
    page: int = Query(default=1, ge=1, le=10_000),
    page_size: int = Query(default=20, ge=1, le=100),
    repo: WalletRepository = Depends(get_wallet_repository),
):
    """Return one page of the richest members, ranked by balance descending.

    Rank is computed from the page offset so it stays correct across pages.
    User IDs go out as strings (snowflake precision).
    """
    rows, total = await repo.leaderboard(guild.id, limit=page_size, offset=(page - 1) * page_size)
    items = [
        WalletLeaderboardEntryOut(
            rank=(page - 1) * page_size + i + 1, user_id=str(r.user_id), balance=r.balance
        )
        for i, r in enumerate(rows)
    ]
    return WalletLeaderboardPageOut(items=items, total=total, page=page, page_size=page_size)


@router.get("/{guild_id}/currency/members/{user_id}", response_model=WalletMemberOut)
async def get_member(
    user_id: int = Path(...),
    guild: Guild = Depends(require_managed_guild),
    repo: WalletRepository = Depends(get_wallet_repository),
):
    """Return one member's wallet (rank + balance).

    A member who has never had a wallet reports balance 0 and rank 0 rather
    than 404 — the dashboard can render any user without pre-seeding.
    `user_id` is parsed from the snowflake string in the path.
    """
    wallet = await repo.get(guild.id, user_id)
    balance = wallet.balance if wallet else 0
    rank = await repo.rank_of(guild.id, user_id) or 0
    return WalletMemberOut(user_id=str(user_id), rank=rank, balance=balance)


@router.patch("/{guild_id}/currency/members/{user_id}", response_model=WalletMemberOut)
async def update_member(
    payload: WalletBalanceUpdate,
    user_id: int = Path(...),
    guild: Guild = Depends(require_managed_guild),
    repo: WalletRepository = Depends(get_wallet_repository),
):
    """Admin-override a member's absolute balance (creates the wallet if needed)."""
    await repo.set_balance(guild.id, user_id, payload.balance)
    rank = await repo.rank_of(guild.id, user_id) or 0
    return WalletMemberOut(user_id=str(user_id), rank=rank, balance=payload.balance)


@router.delete("/{guild_id}/currency/members/{user_id}", response_model=WalletMemberOut)
async def reset_member(
    user_id: int = Path(...),
    guild: Guild = Depends(require_managed_guild),
    repo: WalletRepository = Depends(get_wallet_repository),
):
    """Reset a member's balance to zero (admin action)."""
    await repo.set_balance(guild.id, user_id, 0)
    rank = await repo.rank_of(guild.id, user_id) or 0
    return WalletMemberOut(user_id=str(user_id), rank=rank, balance=0)
