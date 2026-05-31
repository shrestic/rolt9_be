"""Claw Agent cog — hội thoại on_message + lệnh quản trị trí nhớ.

Phản hồi khi bot được @mention (cuộc mới) hoặc khi user reply vào tin của bot
(nối tiếp cuộc). Gating: enabled + agent_enabled + (agent_channel_id None hoặc trùng
kênh). Cooldown/user chống spam. Cần intents.message_content (đã bật).
"""

import logging
import time
import uuid

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
    """True nếu tin nhắm tới bot: @mention bot, hoặc là 1 reply (có reference)."""
    if any(getattr(u, "id", None) == bot_user.id for u in message.mentions):
        return True
    return message.reference is not None


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

        async with session_scope() as session:
            guild = await GuildRepository(session).get_by_discord_id(int(message.guild.id))
            if guild is None:
                return
            cfg = await AIConfigRepository(session).get(guild.id)
            if cfg is None or not cfg.enabled or not cfg.agent_enabled:
                return
            if cfg.agent_channel_id and int(message.channel.id) != cfg.agent_channel_id:
                return

            # Conversation: reply tới tin bot -> nối tiếp; còn lại -> cuộc mới.
            msg_repo = AgentMessageRepository(session)
            conversation_id = None
            if message.reference and message.reference.message_id:
                conversation_id = await msg_repo.conversation_of(int(message.reference.message_id))
            if conversation_id is None:
                conversation_id = uuid.uuid4()

            svc = _build_service(session)
            user_text = message.clean_content
            try:
                text = await svc.reply(
                    guild_discord_id=int(message.guild.id),
                    user_discord_id=int(message.author.id),
                    conversation_id=conversation_id,
                    user_name=getattr(message.author, "display_name", str(message.author)),
                    message_text=user_text,
                )
            except ValueError as e:
                await self._safe_reply(message, f"❌ {e}")
                return

            self.cooldown.mark(message.author.id, now=now)
            sent = await self._safe_reply(message, text)
            if sent is None:
                return
            old_facts = await svc.memory_repo.get_facts(guild.id, int(message.author.id))
            await svc.persist(
                guild.id, conversation_id, user_text, text, bot_message_id=int(sent.id)
            )
            await svc.extract_memory(
                int(message.guild.id), int(message.author.id), user_text, text, old_facts
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
