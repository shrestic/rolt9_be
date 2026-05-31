"""Claw Agent cog — hội thoại on_message + lệnh quản trị trí nhớ.

Phản hồi khi bot được @mention (cuộc mới) hoặc khi user reply vào tin của bot
(nối tiếp cuộc). Gating: enabled + agent_enabled + (agent_channel_id None hoặc trùng
kênh). Cooldown/user chống spam. Cần intents.message_content (đã bật).
"""

import logging
import time

import discord
from discord import app_commands
from discord.ext import commands

from app.db.session import session_scope
from app.discord_io.client import DiscordClient
from app.discord_io.errors import DiscordError
from app.repositories.agent_message import AgentMessageRepository
from app.repositories.ai_config import AIConfigRepository
from app.repositories.ai_usage import AIUsageRepository
from app.repositories.guild import GuildRepository
from app.repositories.user_memory import UserMemoryRepository
from app.services.ai.agent_service import AgentService
from app.services.ai.ai_gateway import AIGateway
from app.services.ai.provider import get_ai_provider

log = logging.getLogger(__name__)

AGENT_COOLDOWN = 5.0  # giây giữa 2 tin của cùng 1 user


def is_addressed(message, bot_user) -> bool:
    """True nếu tin nhắm tới bot:
    - @mention user bot thật, hoặc reply (có reference);
    - mention ROLE của bot (role tự sinh trùng tên bot) — qua role_mentions;
    - tin BẮT ĐẦU bằng tên bot dạng text/render (vd '@rolt9 ...'/'rolt9 ...').
    """
    if any(getattr(u, "id", None) == bot_user.id for u in message.mentions):
        return True
    if message.reference is not None:
        return True
    # Mention role của chính bot (guild.me có role đó).
    me = getattr(getattr(message, "guild", None), "me", None)
    role_mentions = getattr(message, "role_mentions", None) or []
    if me is not None and role_mentions:
        my_role_ids = {getattr(r, "id", None) for r in getattr(me, "roles", [])}
        if any(getattr(r, "id", None) in my_role_ids for r in role_mentions):
            return True
    # Tên bot ở đầu tin — check cả clean_content (đã render "@rolt9") lẫn content thô.
    name = (getattr(bot_user, "name", "") or "").lower()
    if name:
        for attr in ("clean_content", "content"):
            text = (getattr(message, attr, "") or "").lstrip().lower()
            if text.startswith(f"@{name}") or text.startswith(name):
                return True
    return False


class CooldownTracker:
    """Cooldown/user trong bộ nhớ (rolt9 chạy 1 process)."""

    def __init__(self, seconds: float):
        self._seconds = seconds
        self._last: dict[int, float] = {}

    def ready(self, user_id: int, *, now: float) -> bool:
        last = self._last.get(user_id)
        return last is None or (now - last) >= self._seconds

    def mark(self, user_id: int, *, now: float) -> None:
        self._last[user_id] = now


def _build_service(session) -> AgentService:
    gateway = AIGateway(
        guild_repo=GuildRepository(session),
        config_repo=AIConfigRepository(session),
        usage_repo=AIUsageRepository(session),
        provider=get_ai_provider(),
    )
    return AgentService(
        guild_repo=GuildRepository(session),
        config_repo=AIConfigRepository(session),
        agent_msg_repo=AgentMessageRepository(session),
        memory_repo=UserMemoryRepository(session),
        gateway=gateway,
    )


class AgentCog(commands.Cog):
    def __init__(self, bot: commands.Bot, discord_io: DiscordClient):
        self.bot = bot
        self.discord_io = discord_io
        self.cooldown = CooldownTracker(AGENT_COOLDOWN)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        if self.bot.user is None or not is_addressed(message, self.bot.user):
            return

        now = time.monotonic()
        if not self.cooldown.ready(message.author.id, now=now):
            return

        user_text = message.clean_content
        ref_id = (
            int(message.reference.message_id)
            if message.reference and message.reference.message_id
            else None
        )
        g = message.guild
        server_snapshot = {
            "member_count": getattr(g, "member_count", 0) or 0,
            "roles": [r.name for r in getattr(g, "roles", []) if r.name != "@everyone"][:50],
            "channels": [c.name for c in getattr(g, "channels", [])][:50],
        }
        async with session_scope() as session:
            svc = _build_service(session)
            try:
                result = await svc.respond(
                    guild_discord_id=int(message.guild.id),
                    channel_id=int(message.channel.id),
                    user_discord_id=int(message.author.id),
                    user_name=getattr(message.author, "display_name", str(message.author)),
                    message_text=user_text,
                    reference_message_id=ref_id,
                    server_snapshot=server_snapshot,
                )
            except ValueError as e:
                await self._safe_reply(message, f"❌ {e}")
                return
            except Exception:
                log.exception("agent: respond crashed")
                return
            if result is None:
                return

            conversation_id, text = result
            self.cooldown.mark(message.author.id, now=now)
            sent = await self._safe_reply(message, text)
            if sent is None:
                return
            await svc.remember(
                guild_discord_id=int(message.guild.id),
                conversation_id=conversation_id,
                user_discord_id=int(message.author.id),
                user_text=user_text,
                assistant_text=text,
                bot_message_id=int(sent.id),
            )

    async def _safe_reply(self, message, content: str):
        try:
            return await message.reply(content[:2000], mention_author=False)
        except (DiscordError, discord.DiscordException):
            log.warning("agent: failed to reply in channel %s", message.channel.id)
            return None

    @app_commands.command(
        name="claw-forget", description="Xoá trí nhớ bot đang giữ về bạn (server này)"
    )
    async def claw_forget(self, interaction: discord.Interaction) -> None:
        async with session_scope() as session:
            guild = await GuildRepository(session).get_by_discord_id(int(interaction.guild_id))
            if guild is not None:
                await UserMemoryRepository(session).clear(guild.id, int(interaction.user.id))
        await interaction.response.send_message("🧹 Đã xoá trí nhớ về bạn.", ephemeral=True)

    @app_commands.command(name="claw-memory", description="Xem bot đang nhớ gì về bạn (server này)")
    async def claw_memory(self, interaction: discord.Interaction) -> None:
        facts = ""
        async with session_scope() as session:
            guild = await GuildRepository(session).get_by_discord_id(int(interaction.guild_id))
            if guild is not None:
                facts = await UserMemoryRepository(session).get_facts(
                    guild.id, int(interaction.user.id)
                )
        await interaction.response.send_message(facts or "Mình chưa nhớ gì về bạn.", ephemeral=True)
