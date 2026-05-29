# Slash commands for leveling. All read-only — admins mutate settings through
# the dashboard endpoints, not slash commands. Reply messages are public so
# rank cards render in-channel.

import logging
from collections.abc import Awaitable, Callable
from io import BytesIO

import discord
from discord import app_commands
from discord.ext import commands

from app.core.colors import RankCardColors
from app.db.session import AsyncSessionLocal, session_scope
from app.discord_io.client import DiscordClient
from app.discord_io.errors import DiscordError
from app.repositories.guild import GuildRepository
from app.repositories.guild_rank_card_theme import GuildRankCardThemeRepository
from app.repositories.level_role_reward import LevelRoleRewardRepository
from app.repositories.leveling_config import GuildLevelingConfigRepository
from app.repositories.user_xp import UserXpRepository
from app.services.leveling import LevelingService, RankCardRenderer

log = logging.getLogger(__name__)


def _build_service(session, discord_io: DiscordClient) -> LevelingService:
    return LevelingService(
        session=session,
        discord_io=discord_io,
        guild_repo=GuildRepository(session),
        config_repo=GuildLevelingConfigRepository(session),
        xp_repo=UserXpRepository(session),
        reward_repo=LevelRoleRewardRepository(session),
        theme_repo=GuildRankCardThemeRepository(session),
    )


# Mirrors moderation.py::_run_action — same defer + try/except + followup shape.
async def _run_action(
    interaction: discord.Interaction,
    discord_io: DiscordClient,
    action: Callable[[LevelingService], Awaitable[None]],
) -> None:
    await interaction.response.defer()
    try:
        async with session_scope() as session:
            service = _build_service(session, discord_io)
            await action(service)
    except ValueError as exc:
        await interaction.followup.send(f"❌ {exc}", ephemeral=True)
    except LookupError as exc:
        await interaction.followup.send(f"❌ {exc}", ephemeral=True)
    except DiscordError as exc:
        log.warning("Discord action failed: %s", exc)
        await interaction.followup.send(
            f"❌ Discord rejected the action ({type(exc).__name__}).", ephemeral=True
        )


class LevelingCog(commands.Cog):
    def __init__(self, bot: commands.Bot, discord_io: DiscordClient):
        self.bot = bot
        self.discord_io = discord_io
        self._renderer = RankCardRenderer()

    @app_commands.command(name="rank", description="Show your (or someone else's) rank card.")
    async def rank(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
    ) -> None:
        target = member or interaction.user
        if interaction.guild is None:
            await interaction.response.send_message(
                "Rank cards are only available in servers.", ephemeral=True
            )
            return

        async def do(service: LevelingService) -> None:
            data = await service.build_rank_card_data(
                guild_discord_id=int(interaction.guild.id),
                user_id=int(target.id),
                username=target.display_name,
            )
            if data is None:
                await interaction.followup.send("This server is not registered.", ephemeral=True)
                return
            theme = await service.get_theme(
                guild_discord_id=int(interaction.guild.id), user_id=int(target.id)
            )
            png = await self._renderer.render_async(data, theme)
            await interaction.followup.send(file=discord.File(BytesIO(png), filename="rank.png"))

        await _run_action(interaction, self.discord_io, do)

    @app_commands.command(name="leaderboard", description="Show the server XP leaderboard.")
    async def leaderboard(self, interaction: discord.Interaction, page: int = 1) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Leaderboards are only available in servers.", ephemeral=True
            )
            return
        if page < 1:
            page = 1

        page_size = 10

        async def do(service: LevelingService) -> None:
            from app.repositories.guild import GuildRepository

            async with AsyncSessionLocal() as session:
                guild_row = await GuildRepository(session).get_by_discord_id(
                    int(interaction.guild.id)
                )
                if guild_row is None:
                    await interaction.followup.send(
                        "This server is not registered.", ephemeral=True
                    )
                    return
                page_data = await service.leaderboard(
                    guild_id=guild_row.id, limit=page_size, offset=(page - 1) * page_size
                )
            lines = [
                f"`#{e.rank}` <@{e.user_id}> — Level **{e.level}** ({e.total_xp:,} XP)"
                for e in page_data.items
            ]
            body = "\n".join(lines) if lines else "_No XP records yet._"
            embed = discord.Embed(
                title=f"Leaderboard — page {page}",
                description=body,
                color=RankCardColors.DEFAULT_ACCENT_INT,
            )
            embed.set_footer(text=f"{page_data.total} members tracked")
            await interaction.followup.send(embed=embed)

        await _run_action(interaction, self.discord_io, do)

    @app_commands.command(
        name="level-rewards", description="Show this server's level → role rewards."
    )
    async def level_rewards(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Level rewards are only available in servers.", ephemeral=True
            )
            return

        async def do(service: LevelingService) -> None:
            from app.repositories.guild import GuildRepository

            async with AsyncSessionLocal() as session:
                guild_row = await GuildRepository(session).get_by_discord_id(
                    int(interaction.guild.id)
                )
                if guild_row is None:
                    await interaction.followup.send(
                        "This server is not registered.", ephemeral=True
                    )
                    return
                rewards = await LevelRoleRewardRepository(session).list_by_guild(guild_row.id)
            lines = [f"Level **{r.level}** → <@&{r.role_id}>" for r in rewards]
            body = "\n".join(lines) if lines else "_No rewards configured yet._"
            await interaction.followup.send(
                embed=discord.Embed(
                    title="Level Rewards",
                    description=body,
                    color=RankCardColors.DEFAULT_ACCENT_INT,
                )
            )

        await _run_action(interaction, self.discord_io, do)
