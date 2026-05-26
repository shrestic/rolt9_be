# Endpoints for info about the current user:
#   GET /me         → user profile (from DB)
#   GET /me/guilds  → guilds the user can manage, plus a flag for whether the bot is there

from fastapi import APIRouter, Depends

from app.dependencies.auth import get_current_user
from app.dependencies.services import (
    get_guild_repository,
    get_oauth_session_service,
    get_permission_service,
    get_user_repository,
)
from app.models.user import User
from app.repositories.guild import GuildRepository
from app.repositories.user import UserRepository
from app.schemas.guild import GuildSummary
from app.schemas.user import UserOut
from app.services.oauth_session import OAuthSessionService
from app.services.permission_service import PermissionService

router = APIRouter()


# Profile straight from the DB. No Discord call — the info was fetched during
# the OAuth callback.
@router.get("", response_model=UserOut)
async def me(current: User = Depends(get_current_user)):
    return UserOut(
        id=str(current.id),
        discord_id=current.discord_id,
        username=current.username,
        avatar_url=current.avatar_url,
    )


# Flow:
#   1. Get a valid access token (refreshed if needed) via OAuthSessionService
#   2. Ask Discord for the user's guilds → filter to guilds the user manages
#   3. Check the DB for which of those guilds the bot is actively in
#   4. Return GuildSummary objects with the bot_present flag
#
# The FE uses this list to render the "Choose a server to manage" dashboard.
@router.get("/guilds", response_model=list[GuildSummary])
async def my_guilds(
    current: User = Depends(get_current_user),
    perms: PermissionService = Depends(get_permission_service),
    guilds: GuildRepository = Depends(get_guild_repository),
    oauth_session: OAuthSessionService = Depends(get_oauth_session_service),
    users: UserRepository = Depends(get_user_repository),
):
    access_token = await oauth_session.get_valid_access_token(current, users)
    managed = await perms.list_my_managed_guilds(access_token)

    # Check which of the managed guilds the bot is active in. One batch query.
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
