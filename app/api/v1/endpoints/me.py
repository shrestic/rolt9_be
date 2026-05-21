from fastapi import APIRouter, Depends

from app.dependencies.auth import get_current_user
from app.dependencies.services import (
    get_guild_repository,
    get_oauth_service,
    get_permission_service,
    get_user_repository,
)
from app.models.user import User
from app.repositories.guild import GuildRepository
from app.repositories.user import UserRepository
from app.schemas.guild import GuildSummary
from app.schemas.user import UserOut
from app.services.discord_oauth import DiscordOAuthService
from app.services.permission_service import PermissionService

router = APIRouter()


@router.get("", response_model=UserOut)
async def me(current: User = Depends(get_current_user)):
    return UserOut(
        id=str(current.id),
        discord_id=current.discord_id,
        username=current.username,
        avatar_url=current.avatar_url,
    )


@router.get("/guilds", response_model=list[GuildSummary])
async def my_guilds(
    current: User = Depends(get_current_user),
    perms: PermissionService = Depends(get_permission_service),
    guilds: GuildRepository = Depends(get_guild_repository),
    oauth: DiscordOAuthService = Depends(get_oauth_service),
    users: UserRepository = Depends(get_user_repository),
):
    access_token = await oauth.get_valid_access_token(current, users)
    managed = await perms.list_my_managed_guilds(access_token)
    present_ids = {
        g.discord_id
        for g in await guilds.get_active_by_discord_ids([m.discord_id for m in managed])
    }
    return [
        GuildSummary(
            discord_id=str(m.discord_id),
            name=m.name,
            icon_url=m.icon_url,
            bot_present=m.discord_id in present_ids,
            can_manage=True,
        )
        for m in managed
    ]
