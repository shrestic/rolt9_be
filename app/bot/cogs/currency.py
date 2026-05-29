"""Slash commands for server currency.

Thin layer over CurrencyService (mirrors LevelingCog): defer → session_scope →
build service → act → reply. All money logic + validation lives in the service,
so these handlers just translate Discord interactions to service calls and shape
the reply. Service errors map to a friendly ❌ message via `_run`.
"""

import logging
from collections.abc import Awaitable, Callable

import discord
from discord import app_commands
from discord.ext import commands

from app.db.session import session_scope
from app.discord_io.client import DiscordClient
from app.repositories.currency_config import CurrencyConfigRepository
from app.repositories.guild import GuildRepository
from app.repositories.user_wallet import WalletRepository
from app.services.currency import CurrencyService

log = logging.getLogger(__name__)


def _build_service(session) -> CurrencyService:
    return CurrencyService(
        session=session,
        guild_repo=GuildRepository(session),
        config_repo=CurrencyConfigRepository(session),
        wallet_repo=WalletRepository(session),
    )


async def _run(
    interaction: discord.Interaction,
    action: Callable[[CurrencyService], Awaitable[str]],
    *,
    ephemeral: bool = False,
) -> None:
    # One transaction per command (UoW). The action returns the reply string;
    # any user-facing rejection (ValueError) or unregistered guild (LookupError)
    # becomes an ephemeral ❌ message instead of a crash.
    await interaction.response.defer(ephemeral=ephemeral)
    try:
        async with session_scope() as session:
            msg = await action(_build_service(session))
        await interaction.followup.send(msg, ephemeral=ephemeral)
    except (ValueError, LookupError) as exc:
        await interaction.followup.send(f"❌ {exc}", ephemeral=True)


async def _label(service: CurrencyService, guild_discord_id: int) -> str:
    """Return the guild's currency emoji (falls back to a coin) for messages."""
    guild = await service.guild_repo.get_by_discord_id(guild_discord_id)
    if guild is None:
        return "🪙"
    cfg = await service.config_repo.get(guild.id)
    return cfg.currency_emoji if cfg else "🪙"


class CurrencyCog(commands.Cog):
    def __init__(self, bot: commands.Bot, discord_io: DiscordClient):
        self.bot = bot
        self.discord_io = discord_io

    @app_commands.command(name="balance", description="Check a wallet balance.")
    @app_commands.guild_only()
    async def balance(
        self, interaction: discord.Interaction, member: discord.Member | None = None
    ) -> None:
        target = member or interaction.user

        async def do(service: CurrencyService) -> str:
            gid = interaction.guild_id
            bal = await service.get_balance(guild_discord_id=gid, user_id=target.id)
            emoji = await _label(service, gid)
            return f"{target.mention} có **{bal:,}** {emoji}"

        await _run(interaction, do)

    @app_commands.command(name="daily", description="Claim your daily reward.")
    @app_commands.guild_only()
    async def daily(self, interaction: discord.Interaction) -> None:
        async def do(service: CurrencyService) -> str:
            gid = interaction.guild_id
            res = await service.claim_daily(guild_discord_id=gid, user_id=interaction.user.id)
            emoji = await _label(service, gid)
            if not res.claimed:
                hrs, mins = divmod(res.retry_after_seconds // 60, 60)
                return f"⏳ Đợi thêm {hrs}h {mins}m nữa."
            # First line: total amount + new balance.
            lines = [f"+{res.amount:,} {emoji}! Số dư: **{res.balance:,}** {emoji}"]
            # Streak line: show breakdown when there's a bonus, otherwise just
            # the chain length so the player always sees their progress.
            if res.streak_bonus:
                lines.append(
                    f"🔥 Chuỗi **{res.streak}** ngày "
                    f"(base {res.base:,} + streak +{res.streak_bonus:,})."
                )
            elif res.streak:
                lines.append(f"🔥 Chuỗi **{res.streak}** ngày.")
            # Milestone line: congrats if one was just hit, otherwise a nudge
            # showing how many days remain before the next reward.
            if res.milestone_bonus:
                lines.append(
                    f"🎉 Mốc **{res.streak} ngày**! Thưởng **+{res.milestone_bonus:,}** {emoji}."
                )
            elif res.days_to_milestone is not None:
                lines.append(f"⏭️ Còn **{res.days_to_milestone}** ngày tới mốc kế.")
            return "\n".join(lines)

        await _run(interaction, do, ephemeral=True)

    @app_commands.command(name="streak", description="Check a daily-claim streak.")
    @app_commands.guild_only()
    async def streak(
        self, interaction: discord.Interaction, member: discord.Member | None = None
    ) -> None:
        # Allow peeking at another member's streak; default to the invoker.
        target = member or interaction.user

        async def do(service: CurrencyService) -> str:
            gid = interaction.guild_id
            info = await service.get_streak(guild_discord_id=gid, user_id=target.id)
            if not info.enabled:
                # Streak feature is toggled off for this server.
                return "Streak đang tắt trên server này."
            if info.current == 0:
                return f"{target.mention} chưa có chuỗi nào. Gõ `/daily` để bắt đầu!"
            lines = [
                f"🔥 {target.mention} đang giữ chuỗi **{info.current}** ngày.",
                f"🏆 Kỷ lục: **{info.longest}** ngày.",
            ]
            if info.days_to_milestone is not None:
                lines.append(f"⏭️ Còn **{info.days_to_milestone}** ngày tới mốc kế.")
            else:
                lines.append("👑 Đã đạt mốc cao nhất!")
            return "\n".join(lines)

        await _run(interaction, do)

    @app_commands.command(name="pay", description="Send currency to another member.")
    @app_commands.guild_only()
    async def pay(
        self, interaction: discord.Interaction, member: discord.Member, amount: int
    ) -> None:
        async def do(service: CurrencyService) -> str:
            if member.bot:
                raise ValueError("You can't pay a bot.")
            gid = interaction.guild_id
            await service.pay(
                guild_discord_id=gid,
                sender_id=interaction.user.id,
                receiver_id=member.id,
                amount=amount,
            )
            emoji = await _label(service, gid)
            return f"Đã chuyển **{amount:,}** {emoji} cho {member.mention}."

        await _run(interaction, do)

    @app_commands.command(name="baltop", description="Richest members in this server.")
    @app_commands.guild_only()
    async def baltop(self, interaction: discord.Interaction) -> None:
        async def do(service: CurrencyService) -> str:
            gid = interaction.guild_id
            rows, _ = await service.leaderboard(guild_discord_id=gid, limit=10, offset=0)
            emoji = await _label(service, gid)
            if not rows:
                return "Chưa ai có tiền."
            lines = [
                f"**{i + 1}.** <@{r.user_id}> — {r.balance:,} {emoji}" for i, r in enumerate(rows)
            ]
            return "\n".join(lines)

        await _run(interaction, do)

    eco = app_commands.Group(
        name="eco",
        description="Economy admin",
        default_permissions=discord.Permissions(manage_guild=True),
        guild_only=True,
    )

    @eco.command(name="give", description="Give currency to a member.")
    async def eco_give(
        self, interaction: discord.Interaction, member: discord.Member, amount: int
    ) -> None:
        async def do(service: CurrencyService) -> str:
            gid = interaction.guild_id
            bal = await service.admin_add(guild_discord_id=gid, user_id=member.id, delta=amount)
            emoji = await _label(service, gid)
            return f"Đã cộng **{amount:,}** {emoji} cho {member.mention} (số dư {bal:,})."

        await _run(interaction, do)

    @eco.command(name="take", description="Take currency from a member.")
    async def eco_take(
        self, interaction: discord.Interaction, member: discord.Member, amount: int
    ) -> None:
        async def do(service: CurrencyService) -> str:
            gid = interaction.guild_id
            bal = await service.admin_add(guild_discord_id=gid, user_id=member.id, delta=-amount)
            emoji = await _label(service, gid)
            return f"Đã trừ **{amount:,}** {emoji} của {member.mention} (số dư {bal:,})."

        await _run(interaction, do)

    @eco.command(name="reset", description="Reset a member's wallet to zero.")
    async def eco_reset(self, interaction: discord.Interaction, member: discord.Member) -> None:
        async def do(service: CurrencyService) -> str:
            gid = interaction.guild_id
            await service.admin_set(guild_discord_id=gid, user_id=member.id, value=0)
            return f"Đã reset ví {member.mention} về 0."

        await _run(interaction, do)
