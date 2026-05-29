# on_message handler that drives the leveling system. We keep handle_message as
# a stand-alone function (rather than nesting it inside the cog) so it's testable
# without spinning up a discord.py runtime — handle_message takes plain dataclass-
# shaped inputs.
#
# The cog (registered separately) just calls handle_message inside an
# @commands.Cog.listener() and provides the per-call db session.

import logging
from collections.abc import Callable

import discord
from discord.ext import commands

from app.bot.cache.leveling_config_cache import CachedLevelingConfig, LevelingConfigCache
from app.db.session import session_scope
from app.discord_io.client import DiscordClient
from app.repositories.currency_config import CurrencyConfigRepository
from app.repositories.guild import GuildRepository
from app.repositories.guild_rank_card_theme import GuildRankCardThemeRepository
from app.repositories.level_role_reward import LevelRoleRewardRepository
from app.repositories.leveling_config import GuildLevelingConfigRepository
from app.repositories.user_wallet import WalletRepository
from app.repositories.user_xp import UserXpRepository
from app.services.currency import CurrencyService
from app.services.leveling import LevelingService

log = logging.getLogger(__name__)


async def handle_message(
    message,
    *,
    cache: LevelingConfigCache,
    service_factory: Callable[[], LevelingService],
    currency_factory: Callable[[], CurrencyService] | None = None,
) -> None:
    # Skip bots and DMs up front — the absolute cheapest gate.
    if getattr(message.author, "bot", False):
        return
    if message.guild is None:
        return

    config: CachedLevelingConfig | None = await cache.get(int(message.guild.id))
    if config is None or not config.enabled:
        return

    service = service_factory()
    outcome = await service.process_message(
        guild_discord_id=int(message.guild.id),
        user_id=int(message.author.id),
        username=getattr(message.author, "display_name", str(message.author)),
        content=message.content or "",
        channel_id=int(message.channel.id),
        member_role_ids=[int(r.id) for r in getattr(message.author, "roles", [])],
    )

    # Piggyback: currency is granted only when XP was actually awarded (i.e. the
    # message passed every anti-spam + cooldown gate). Reuses those gates for free.
    if outcome is not None and currency_factory is not None:
        await currency_factory().grant_message_reward(
            guild_discord_id=int(message.guild.id),
            user_id=int(message.author.id),
        )


# Cog wrapper — picks up on_message and dispatches to handle_message.
# Listener (rather than full cog) because the bot already routes on_message
# through CustomCommandsCog as well; both run because discord.py fans the
# event out to every Cog with a listener for it.
class XpListenerCog(commands.Cog):
    def __init__(self, bot: commands.Bot, cache: LevelingConfigCache, discord_io: DiscordClient):
        self.bot = bot
        self.cache = cache
        self.discord_io = discord_io

    def _build_service(self, session) -> LevelingService:
        return LevelingService(
            session=session,
            discord_io=self.discord_io,
            guild_repo=GuildRepository(session),
            config_repo=GuildLevelingConfigRepository(session),
            xp_repo=UserXpRepository(session),
            reward_repo=LevelRoleRewardRepository(session),
            theme_repo=GuildRankCardThemeRepository(session),
        )

    def _build_currency(self, session) -> CurrencyService:
        return CurrencyService(
            session=session,
            guild_repo=GuildRepository(session),
            config_repo=CurrencyConfigRepository(session),
            wallet_repo=WalletRepository(session),
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        async with session_scope() as session:
            service = self._build_service(session)
            currency = self._build_currency(session)
            await handle_message(
                message,
                cache=self.cache,
                service_factory=lambda: service,
                currency_factory=lambda: currency,
            )
