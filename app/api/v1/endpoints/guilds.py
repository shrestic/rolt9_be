# Endpoint that provides a guild overview for the dashboard:
#   - Name + icon + member_count
#   - List of channels (so admins can pick a mod-log channel)
#   - List of roles (so admins can pick which roles may run commands)

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies.auth import get_current_user
from app.dependencies.services import (
    get_discord_io,
    get_oauth_session_service,
    get_permission_service,
    get_user_repository,
)
from app.discord_io.client import DiscordClient
from app.models.user import User
from app.repositories.user import UserRepository
from app.schemas.guild import ChannelDTO, GuildOverview, RoleDTO
from app.services.oauth_session import OAuthSessionService
from app.services.permission_service import PermissionService

router = APIRouter()


# Flow:
#   1. Auth: user is logged in + has manage permission on this guild
#   2. Fetch guild info / channels / roles from Discord via DiscordClient (bot token)
#   3. Format the response
#
# We don't use require_managed_guild here because this endpoint doesn't check
# "the bot is in the guild" (the FE shows overview even when the bot hasn't
# joined yet). In practice the bot must be in the guild, since requesting the
# guild info with a bot token will fail otherwise.
@router.get("/{guild_id}/overview", response_model=GuildOverview)
async def guild_overview(
    guild_id: str,
    current: User = Depends(get_current_user),
    perms: PermissionService = Depends(get_permission_service),
    oauth_session: OAuthSessionService = Depends(get_oauth_session_service),
    users: UserRepository = Depends(get_user_repository),
    discord_io: DiscordClient = Depends(get_discord_io),
):
    # Step 1: authenticate the user + check permission
    access_token = await oauth_session.get_valid_access_token(current, users)
    if not await perms.user_can_manage(access_token, guild_id):
        raise HTTPException(status_code=403, detail="You don't manage this server")

    # Step 2: fetch from Discord — 3 separate calls.
    # (If performance becomes a concern, use asyncio.gather. Sequential is fine
    # for now.)
    gid = int(guild_id)
    guild = await discord_io.get_guild(gid)
    channels = await discord_io.list_channels(gid)
    roles = await discord_io.list_roles(gid)

    # Step 3: format
    return GuildOverview(
        discord_id=str(guild.discord_id),
        name=guild.name,
        icon_url=guild.icon_url,
        member_count=guild.member_count,
        channels=[ChannelDTO(id=str(c.discord_id), name=c.name, type=c.type) for c in channels],
        roles=[RoleDTO(id=str(r.discord_id), name=r.name) for r in roles],
        bot_present=True,
    )
