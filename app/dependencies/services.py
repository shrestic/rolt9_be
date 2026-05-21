from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.repositories.guild import GuildRepository
from app.repositories.guild_settings import GuildSettingsRepository
from app.repositories.user import UserRepository
from app.services.discord_oauth import DiscordOAuthService
from app.services.permission_service import PermissionService


def get_user_repository(db: AsyncSession = Depends(get_db)) -> UserRepository:
    return UserRepository(db)


def get_guild_repository(db: AsyncSession = Depends(get_db)) -> GuildRepository:
    return GuildRepository(db)


def get_guild_settings_repository(db: AsyncSession = Depends(get_db)) -> GuildSettingsRepository:
    return GuildSettingsRepository(db)


# Singletons — PermissionService keeps in-memory cache, OAuth client is stateless
_oauth_svc = DiscordOAuthService()
_perm_svc = PermissionService()


def get_oauth_service() -> DiscordOAuthService:
    return _oauth_svc


def get_permission_service() -> PermissionService:
    return _perm_svc
