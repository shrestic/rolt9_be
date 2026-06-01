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
from app.repositories.memory_doc import MemoryDocRepository
from app.repositories.reminder import ReminderRepository
from app.repositories.subscription import SubscriptionRepository
from app.repositories.user_memory import UserMemoryRepository
from app.services.ai.actions.registry import ACTION_PERMS
from app.services.ai.actions.registry import execute as run_action
from app.services.ai.agent_service import AgentService
from app.services.ai.ai_gateway import AIGateway
from app.services.ai.provider import get_ai_provider

log = logging.getLogger(__name__)

AGENT_COOLDOWN = 5.0  # giây giữa 2 tin của cùng 1 user
CHANNEL_CONTEXT_LIMIT = 12  # số tin gần đây trong kênh nạp cho bot để bám sát hội thoại
_PERM_FLAGS = ("manage_guild", "manage_roles", "ban_members", "kick_members", "moderate_members")


async def collect_channel_context(channel, *, before, limit: int = CHANNEL_CONTEXT_LIMIT) -> str:
    """Đọc vài tin gần đây NHẤT trong kênh (trước tin đang xử lý) thành chuỗi
    'Tên: nội dung' theo thứ tự thời gian, để bot bám sát cuộc trò chuyện đang diễn ra.
    Lỗi đọc lịch sử (thiếu quyền) -> trả chuỗi rỗng, không chặn luồng trả lời."""
    lines: list[str] = []
    try:
        async for m in channel.history(limit=limit, before=before):
            text = (m.clean_content or "").strip().replace("\n", " ")
            if not text:
                continue
            who = getattr(m.author, "display_name", str(m.author))
            lines.append(f"{who}: {text}"[:300])
    except (DiscordError, discord.DiscordException, AttributeError):
        return ""
    lines.reverse()  # history() trả mới->cũ; đảo lại thành cũ->mới cho dễ đọc
    return "\n".join(lines)


def perms_dict(guild_permissions) -> dict:
    """Trích các flag quyền liên quan action thành dict (để gate stage + confirm)."""
    return {f: bool(getattr(guild_permissions, f, False)) for f in _PERM_FLAGS}


def confirm_perm_ok(kind: str, perms: dict) -> bool:
    """Người bấm ✅ có đủ quyền cho action này không (Administrator có sẵn mọi flag)."""
    return bool(perms.get(ACTION_PERMS.get(kind, "")))


class ActionConfirmView(discord.ui.View):
    """Nút ✅/❌ cho hành động PHÁ (ban/kick/timeout/delete_role)."""

    def __init__(self, pending):
        super().__init__(timeout=120)
        self.pending = pending

    @discord.ui.button(label="✅ Xác nhận", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not confirm_perm_ok(self.pending.kind, perms_dict(interaction.user.guild_permissions)):
            await interaction.response.send_message(
                "Bạn không đủ quyền cho hành động này.", ephemeral=True
            )
            return
        async with session_scope() as session:
            res = await run_action(self.pending, guild=interaction.guild, session=session)
        await interaction.response.edit_message(content=f"✅ {res}", view=None)
        self.stop()

    @discord.ui.button(label="❌ Hủy", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="Đã hủy.", view=None)
        self.stop()


def is_addressed(message, bot_user) -> bool:
    """True nếu tin NHẮM TỚI bot:
    - @mention user bot thật;
    - reply vào TIN CỦA BOT (không phải reply người khác);
    - mention ROLE của bot (role tự sinh trùng tên bot) — qua role_mentions;
    - tin BẮT ĐẦU bằng tên bot dạng text/render (vd '@rolt9 ...'/'rolt9 ...').
    """
    if any(getattr(u, "id", None) == bot_user.id for u in message.mentions):
        return True
    # Reply: CHỈ tính khi reply vào tin CỦA BOT. Trước đây nhận MỌI reply -> bot tự nhảy vào
    # rep cả khi 2 người reply qua lại với nhau (không liên quan bot). Đó là con bug.
    ref = getattr(message.reference, "resolved", None) if message.reference else None
    ref_author = getattr(ref, "author", None)
    if ref_author is not None and getattr(ref_author, "id", None) == bot_user.id:
        return True
    # Mention role của chính bot (guild.me có role đó).
    me = getattr(getattr(message, "guild", None), "me", None)
    role_mentions = getattr(message, "role_mentions", None) or []
    if me is not None and role_mentions:
        my_role_ids = {getattr(r, "id", None) for r in getattr(me, "roles", [])}
        if any(getattr(r, "id", None) in my_role_ids for r in role_mentions):
            return True
    # Tên bot ở ĐẦU tin — phải có ranh giới từ sau tên (tránh 'rolt9000...' khớp nhầm 'rolt9').
    name = (getattr(bot_user, "name", "") or "").lower()
    if name:
        for attr in ("clean_content", "content"):
            text = (getattr(message, attr, "") or "").lstrip().lower()
            for prefix in (f"@{name}", name):
                if text.startswith(prefix):
                    rest = text[len(prefix) :]
                    if rest == "" or not rest[0].isalnum():
                        return True
    return False


class CooldownTracker:
    """Cooldown trong bộ nhớ (rolt9 chạy 1 process).

    Key theo (guild_id, user_id) -> mỗi server tính cooldown riêng, nên cùng 1 người
    nhắn bot ở 2 server khác nhau KHÔNG chặn nhầm chéo nhau.
    """

    def __init__(self, seconds: float):
        self._seconds = seconds
        self._last: dict[tuple[int, int], float] = {}

    def ready(self, guild_id: int, user_id: int, *, now: float) -> bool:
        last = self._last.get((guild_id, user_id))
        return last is None or (now - last) >= self._seconds

    def mark(self, guild_id: int, user_id: int, *, now: float) -> None:
        self._last[(guild_id, user_id)] = now


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
        memory_doc_repo=MemoryDocRepository(session),
        reminder_repo=ReminderRepository(session),
        subscription_repo=SubscriptionRepository(session),
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
        # Cooldown theo (guild, user) -> không chặn nhầm khi cùng user nhắn ở server khác.
        if not self.cooldown.ready(int(message.guild.id), message.author.id, now=now):
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
        bot_id = self.bot.user.id if self.bot.user else None
        target_user_ids = [u.id for u in message.mentions if u.id != bot_id]
        # 'Tên = <@id>' cho người được @ -> để bot ghi nhớ KÈM id và tag lại đúng người sau này.
        mention_map = "; ".join(
            f"{getattr(u, 'display_name', None) or u.name} = <@{u.id}>"
            for u in message.mentions
            if u.id != bot_id
        )
        commander_perms = perms_dict(message.author.guild_permissions)
        channel_context = await collect_channel_context(message.channel, before=message)
        async with session_scope() as session:
            svc = _build_service(session)
            try:
                # "rolt9 đang gõ..." trong lúc gọi model (4-8s) -> đỡ cảm giác đơ.
                async with message.channel.typing():
                    result = await svc.respond(
                        guild_discord_id=int(message.guild.id),
                        channel_id=int(message.channel.id),
                        user_discord_id=int(message.author.id),
                        user_name=getattr(message.author, "display_name", str(message.author)),
                        message_text=user_text,
                        reference_message_id=ref_id,
                        server_snapshot=server_snapshot,
                        commander_perms=commander_perms,
                        role_names=[r.name for r in getattr(g, "roles", [])],
                        target_user_ids=target_user_ids,
                        commander_id=int(message.author.id),
                        channel_context=channel_context,
                        mention_map=mention_map,
                    )
            except ValueError as e:
                await self._safe_reply(message, f"❌ {e}")
                return
            except Exception:
                log.exception("agent: respond crashed")
                return
            if result is None:
                return

            conversation_id, text, pending = result
            self.cooldown.mark(int(message.guild.id), message.author.id, now=now)

            if pending:
                # LƯỢT HÀNH ĐỘNG: chạy tool TRƯỚC rồi mới báo theo KẾT QUẢ THẬT — KHÔNG gửi lời
                # model (model hay "báo khống đã làm" trước khi tool chạy). Hành động phá -> nút
                # ✅/❌ (chỉ chạy KHI bấm). create_role chạy trước để "tạo role X rồi gán X" chạy được.
                outcomes: list[str] = []
                last_sent = None
                for p in sorted(pending, key=lambda a: 0 if a.kind == "create_role" else 1):
                    if p.destructive:
                        last_sent = await self._send_confirm(message, p) or last_sent
                        outcomes.append(f"(chờ admin xác nhận) {p.description}")
                    else:
                        res = await run_action(
                            p, guild=message.guild, session=session, channel=message.channel
                        )
                        log.info("agent action executed: kind=%s -> %s", p.kind, res)
                        if p.kind != "create_poll":  # poll tự là output rồi
                            last_sent = await self._safe_reply(message, f"✅ {res}") or last_sent
                        outcomes.append(res)
                # Lưu lượt theo KẾT QUẢ thật (không lưu prose khống của model).
                await svc.remember(
                    guild_discord_id=int(message.guild.id),
                    conversation_id=conversation_id,
                    user_discord_id=int(message.author.id),
                    user_text=user_text,
                    assistant_text=" | ".join(outcomes) or "(đã xử lý)",
                    bot_message_id=int(last_sent.id) if last_sent else 0,
                    channel_id=int(message.channel.id),
                )
            else:
                # LƯỢT CHAT (không hành động): gửi lời model bình thường.
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
                    channel_id=int(message.channel.id),
                )

    async def _send_confirm(self, message, pending):
        """Gửi nút ✅/❌ cho hành động phá. Trả message đã gửi (hoặc None nếu lỗi)."""
        try:
            return await message.channel.send(
                f"🤖 Xác nhận hành động: **{pending.description}**?",
                view=ActionConfirmView(pending),
            )
        except (DiscordError, discord.DiscordException):
            log.warning("agent: failed to send confirm in channel %s", message.channel.id)
            return None

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

    @app_commands.command(
        name="claw-lore", description="Xem trí nhớ chung của server (biệt danh, luật, …)"
    )
    async def claw_lore(self, interaction: discord.Interaction) -> None:
        """Hiển thị memory_doc toàn server. Ai cũng xem được (chỉ đọc)."""
        doc = ""
        async with session_scope() as session:
            guild = await GuildRepository(session).get_by_discord_id(int(interaction.guild_id))
            if guild is not None:
                doc = await MemoryDocRepository(session).get_doc(guild.id)
        await interaction.response.send_message(
            f"📒 **Trí nhớ server:**\n{doc}"
            if doc.strip()
            else "Server chưa có trí nhớ chung nào.",
            ephemeral=True,
        )

    @app_commands.command(
        name="claw-lore-clear",
        description="Xoá toàn bộ trí nhớ chung của server (cần Manage Server)",
    )
    async def claw_lore_clear(self, interaction: discord.Interaction) -> None:
        """Xoá memory_doc. Chỉ người có Manage Server mới được (đây là dữ liệu chung)."""
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                "Bạn cần quyền **Manage Server** để xoá trí nhớ chung.", ephemeral=True
            )
            return
        async with session_scope() as session:
            guild = await GuildRepository(session).get_by_discord_id(int(interaction.guild_id))
            if guild is not None:
                await MemoryDocRepository(session).clear(guild.id)
        await interaction.response.send_message(
            "🧹 Đã xoá trí nhớ chung của server.", ephemeral=True
        )
