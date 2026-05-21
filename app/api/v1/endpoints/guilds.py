from fastapi import APIRouter, Depends, HTTPException

from app.core.config import settings
from app.dependencies.auth import get_current_user
from app.dependencies.services import (
    get_oauth_service,
    get_permission_service,
    get_user_repository,
)
from app.models.user import User
from app.repositories.user import UserRepository
from app.schemas.guild import ChannelDTO, GuildOverview, RoleDTO
from app.services.discord_api import DiscordAPIClient
from app.services.discord_oauth import DiscordOAuthService
from app.services.permission_service import PermissionService

router = APIRouter()


@router.get("/{guild_id}/overview", response_model=GuildOverview)
async def guild_overview(
    guild_id: str,
    current: User = Depends(get_current_user),
    perms: PermissionService = Depends(get_permission_service),
    oauth: DiscordOAuthService = Depends(get_oauth_service),
    users: UserRepository = Depends(get_user_repository),
):
    access_token = await oauth.get_valid_access_token(current, users)
    if not await perms.user_can_manage(access_token, guild_id):
        raise HTTPException(status_code=403, detail="You don't manage this server")

    api = DiscordAPIClient()
    guild = await api.get_guild_with_counts(guild_id, settings.DISCORD_BOT_TOKEN)
    channels = await api.list_guild_channels(guild_id, settings.DISCORD_BOT_TOKEN)
    roles = await api.list_guild_roles(guild_id, settings.DISCORD_BOT_TOKEN)

    icon_url = (
        f"https://cdn.discordapp.com/icons/{guild['id']}/{guild['icon']}.png"
        if guild.get("icon")
        else None
    )

    return GuildOverview(
        discord_id=str(guild["id"]),
        name=guild["name"],
        icon_url=icon_url,
        member_count=guild.get("approximate_member_count", 0),
        channels=[
            ChannelDTO(id=str(c["id"]), name=c["name"], type=c.get("type", 0)) for c in channels
        ],
        roles=[RoleDTO(id=str(r["id"]), name=r["name"]) for r in roles],
        bot_present=True,
    )
