"""Welcome plugin cog — posts join/leave messages.

Listeners on `on_member_join` / `on_member_remove` build the message via
WelcomeService and post it through discord_io. Requires the privileged `members`
intent (enabled in the client; admin must also tick it in the Developer Portal).
Posting failures are swallowed so a bad channel/permission never breaks the event.
"""

import logging

import discord
from discord.ext import commands

from app.db.session import session_scope
from app.discord_io.client import DiscordClient
from app.discord_io.errors import DiscordError
from app.repositories.ai_config import AIConfigRepository
from app.repositories.ai_usage import AIUsageRepository
from app.repositories.guild import GuildRepository
from app.repositories.welcome_config import WelcomeConfigRepository
from app.services.ai.ai_gateway import AIGateway
from app.services.ai.provider import get_ai_provider
from app.services.welcome.welcome_service import WelcomeService

log = logging.getLogger(__name__)


def _build_service(session) -> WelcomeService:
    gateway = AIGateway(
        guild_repo=GuildRepository(session),
        config_repo=AIConfigRepository(session),
        usage_repo=AIUsageRepository(session),
        provider=get_ai_provider(),
    )
    return WelcomeService(
        guild_repo=GuildRepository(session),
        config_repo=WelcomeConfigRepository(session),
        gateway=gateway,
    )


class WelcomeCog(commands.Cog):
    def __init__(self, bot: commands.Bot, discord_io: DiscordClient):
        self.bot = bot
        self.discord_io = discord_io

    async def _post(self, channel_id: int, text: str) -> None:
        try:
            await self.discord_io.post_to_channel(channel_id, content=text)
        except DiscordError:
            log.warning("welcome: failed to post to channel %s", channel_id)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.guild is None:
            return
        async with session_scope() as session:
            result = await _build_service(session).build_welcome(
                guild_discord_id=int(member.guild.id),
                user_mention=member.mention,
                user_name=getattr(member, "display_name", str(member)),
                server_name=member.guild.name,
                member_count=getattr(member.guild, "member_count", 0) or 0,
            )
        if result is not None:
            await self._post(result[0], result[1])

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        if member.guild is None:
            return
        async with session_scope() as session:
            result = await _build_service(session).build_leave(
                guild_discord_id=int(member.guild.id),
                user_name=getattr(member, "display_name", str(member)),
                server_name=member.guild.name,
                member_count=getattr(member.guild, "member_count", 0) or 0,
            )
        if result is not None:
            await self._post(result[0], result[1])
