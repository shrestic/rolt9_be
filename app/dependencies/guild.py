# Dependency used by endpoints that operate within a single guild.
# Enforces three conditions:
#   1. The user is logged in (via get_current_user)
#   2. The user has permission to manage that guild (via PermissionService.user_can_manage)
#   3. The bot is actually in the guild (via GuildRepository.get_by_discord_id)
#
# Returns the Guild ORM row so the handler can use it directly (has both
# internal UUID and Discord ID).

from fastapi import Depends

from app.dependencies.auth import get_current_user
from app.dependencies.services import (
    get_guild_repository,
    get_oauth_session_service,
    get_permission_service,
    get_user_repository,
)
from app.exceptions.http_exceptions import ForbiddenError, NotFoundError
from app.models.guild import Guild
from app.models.user import User
from app.repositories.guild import GuildRepository
from app.repositories.user import UserRepository
from app.services.oauth_session import OAuthSessionService
from app.services.permission_service import PermissionService


async def require_managed_guild(
    guild_id: str,
    current: User = Depends(get_current_user),
    perms: PermissionService = Depends(get_permission_service),
    oauth_session: OAuthSessionService = Depends(get_oauth_session_service),
    users: UserRepository = Depends(get_user_repository),
    guilds: GuildRepository = Depends(get_guild_repository),
) -> Guild:
    # Step 1: get a valid (refreshed if needed) access token.
    access_token = await oauth_session.get_valid_access_token(current, users)

    # Step 2: permission check — does the user have MANAGE_GUILD in this guild?
    if not await perms.user_can_manage(access_token, guild_id):
        raise ForbiddenError(detail="You don't manage this server")

    # Step 3: is the bot actually in this guild? If we don't have a row in the
    # `guilds` table, the bot was never invited (or was kicked) → 404.
    guild = await guilds.get_by_discord_id(int(guild_id))
    if guild is None:
        raise NotFoundError(detail="The bot is not in this server")

    return guild
