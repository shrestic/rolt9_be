# FastAPI DI factories — the functions endpoints use via Depends().
#
# Pattern:
#   - Repo factory: takes a db session (request-scoped) → new instance per request
#   - Service singleton: shared instance (holds cache, http client) → one for the
#     whole app process
#   - DiscordClient: pulled from app.state.bot (the bot started by lifespan) so
#     endpoints share the bot's gateway cache instead of doing REST roundtrips
#   - OAuth client: a small httpx-based client just for OAuth (the bot has no
#     way to exchange user bearer tokens)
#   - Composite service (ModerationService): new per request because it needs
#     the request-scoped db session

import httpx
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.discord_io.client import DiscordClient, DiscordOAuthClient
from app.discord_io.clients.rest import RestDiscordOAuthClient
from app.repositories.badge_config import BadgeConfigRepository
from app.repositories.currency_config import CurrencyConfigRepository
from app.repositories.custom_command import CustomCommandRepository
from app.repositories.guild import GuildRepository
from app.repositories.guild_rank_card_theme import GuildRankCardThemeRepository
from app.repositories.guild_settings import GuildSettingsRepository
from app.repositories.level_role_reward import LevelRoleRewardRepository
from app.repositories.leveling_config import GuildLevelingConfigRepository
from app.repositories.mod_case import ModCaseRepository
from app.repositories.user import UserRepository
from app.repositories.user_badge import BadgeRepository
from app.repositories.user_wallet import WalletRepository
from app.repositories.user_xp import UserXpRepository
from app.services.leveling import LevelingService
from app.services.moderation.service import ModerationService
from app.services.oauth_session import OAuthSessionService
from app.services.permission_service import PermissionService

# ─────────────────────────────────────────────────────────────────────────
# Repositories — new per request (DB session is request-scoped)
# ─────────────────────────────────────────────────────────────────────────


def get_user_repository(db: AsyncSession = Depends(get_db)) -> UserRepository:
    return UserRepository(db)


def get_guild_repository(db: AsyncSession = Depends(get_db)) -> GuildRepository:
    return GuildRepository(db)


def get_guild_settings_repository(db: AsyncSession = Depends(get_db)) -> GuildSettingsRepository:
    return GuildSettingsRepository(db)


def get_mod_case_repository(db: AsyncSession = Depends(get_db)) -> ModCaseRepository:
    return ModCaseRepository(db)


def get_custom_command_repository(db: AsyncSession = Depends(get_db)) -> CustomCommandRepository:
    return CustomCommandRepository(db)


def get_currency_config_repository(
    db: AsyncSession = Depends(get_db),
) -> CurrencyConfigRepository:
    return CurrencyConfigRepository(db)


def get_wallet_repository(db: AsyncSession = Depends(get_db)) -> WalletRepository:
    return WalletRepository(db)


def get_badge_repository(db: AsyncSession = Depends(get_db)) -> BadgeRepository:
    return BadgeRepository(db)


def get_badge_config_repository(db: AsyncSession = Depends(get_db)) -> BadgeConfigRepository:
    return BadgeConfigRepository(db)


# ─────────────────────────────────────────────────────────────────────────
# Discord clients & services — process-wide singletons
# ─────────────────────────────────────────────────────────────────────────

# Shared httpx.AsyncClient used ONLY for OAuth-side calls. Discord bot actions
# go through BotDiscordClient (no httpx involved). Lifecycle: created here at
# module import, closed in main.py's lifespan via close_http_client().
_http: httpx.AsyncClient = httpx.AsyncClient(timeout=10.0)

# Small RestDiscordOAuthClient that handles the OAuth flow only.
# Singletons holding state (cache, refresh policy) are built on top of it.
_oauth_client: RestDiscordOAuthClient = RestDiscordOAuthClient(http=_http)
_oauth_session = OAuthSessionService(oauth=_oauth_client)
_perm_svc = PermissionService(oauth=_oauth_client)


# Called from main.py's lifespan on shutdown — closes the httpx pool.
async def close_http_client() -> None:
    await _http.aclose()


# Reset every in-memory cache held by DI singletons. Tests call this between
# cases so cached state from one test (e.g. a user's managed-guild list)
# doesn't leak into the next.
def reset_caches() -> None:
    _perm_svc._cache.clear()


# Pulls the live BotDiscordClient out of app.state. The bot was started by
# the lifespan in main.py; endpoints share its gateway cache.
# Tests that don't run lifespan override this dependency directly (see conftest).
def get_discord_io(request: Request) -> DiscordClient:
    bot = getattr(request.app.state, "bot", None)
    if bot is None:
        raise RuntimeError(
            "Bot is not running. Either set DISCORD_BOT_TOKEN, or override "
            "get_discord_io in your test setup."
        )
    return bot.discord_io


def get_oauth_client() -> DiscordOAuthClient:
    return _oauth_client


def get_oauth_session_service() -> OAuthSessionService:
    return _oauth_session


def get_permission_service() -> PermissionService:
    return _perm_svc


# ModerationService must be new per request because it needs the request-scoped
# db session. Composed from: db + DiscordClient (from app.state.bot) + 3
# repositories (also request-scoped).
def get_moderation_service(
    db: AsyncSession = Depends(get_db),
    discord_io: DiscordClient = Depends(get_discord_io),
) -> ModerationService:
    return ModerationService(
        session=db,
        discord_io=discord_io,
        guilds=GuildRepository(db),
        settings=GuildSettingsRepository(db),
        cases=ModCaseRepository(db),
    )


def get_leveling_config_repository(
    db: AsyncSession = Depends(get_db),
) -> GuildLevelingConfigRepository:
    return GuildLevelingConfigRepository(db)


def get_user_xp_repository(db: AsyncSession = Depends(get_db)) -> UserXpRepository:
    return UserXpRepository(db)


def get_level_role_reward_repository(
    db: AsyncSession = Depends(get_db),
) -> LevelRoleRewardRepository:
    return LevelRoleRewardRepository(db)


def get_guild_rank_card_theme_repository(
    db: AsyncSession = Depends(get_db),
) -> GuildRankCardThemeRepository:
    return GuildRankCardThemeRepository(db)


def get_leveling_service(
    db: AsyncSession = Depends(get_db),
    discord_io: DiscordClient = Depends(get_discord_io),
) -> LevelingService:
    return LevelingService(
        session=db,
        discord_io=discord_io,
        guild_repo=GuildRepository(db),
        config_repo=GuildLevelingConfigRepository(db),
        xp_repo=UserXpRepository(db),
        reward_repo=LevelRoleRewardRepository(db),
        theme_repo=GuildRankCardThemeRepository(db),
    )
