"""Claw Agent cog — hội thoại on_message + lệnh quản trị trí nhớ.

Phản hồi khi bot được @mention (cuộc mới) hoặc khi user reply vào tin của bot
(nối tiếp cuộc). Gating: enabled + agent_enabled + (agent_channel_id None hoặc trùng
kênh). Cooldown/user chống spam. Cần intents.message_content (đã bật).
"""

import asyncio
import logging
import re
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
# --- Hàng đợi xử lý (nhiều người mention CÙNG LÚC) ---------------------------------
# Trước đây tin tới khi bot đang bận bị BỎ (⏳). Giờ xếp hàng cho một pool worker chạy
# tuần tự -> không drop tin hợp lệ của người khác, mà vẫn chặn được spam.
AGENT_WORKERS = 3  # số lượt agent chạy SONG SONG tối đa (cap bão LLM-call -> giữ DB pool + chi phí)
AGENT_QUEUE_MAX = (
    64  # sức chứa hàng đợi; vượt = cả server quá tải -> drop (⏳) thay vì phình vô hạn
)
AGENT_PER_USER_MAX = (
    2  # 1 người chỉ được xếp tối đa 2 lượt (đang chờ + đang chạy) -> chống 1 người ôm hàng
)
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


def _distinctive(name: str) -> bool:
    """Tên có ĐỦ ĐẶC TRƯNG để auto-tag không (giảm ping nhầm)?

    Username Discord (vd 'thinh.nguyen2') gần như luôn có dấu '.', '_' hoặc số -> rất ít
    đụng từ thường. Tên thuần chữ thì phải dài (>=6) mới tag, để 'minh'/'Đạt' (dễ trùng từ
    tiếng Việt) KHÔNG bị biến nhầm thành mention.
    """
    return len(name) >= 6 or any(c.isdigit() or c in "._" for c in name)


def tag_known_members(text: str, guild, bot_id) -> str:
    """Đổi tên thành viên (username/global_name) xuất hiện trong text thành '<@id>' để bot
    TAG đúng người (ping được), kể cả khi trí nhớ chỉ lưu tên CHỮ TRƠN (không kèm id).

    An toàn: chỉ thay tên ĐẶC TRƯNG (xem _distinctive), đúng ranh giới từ, chưa nằm trong
    '<@...>' sẵn, và mỗi người chỉ thay 1 lần. Lỗi/regex hỏng -> trả text gốc, không chặn gửi.
    """
    if not text or guild is None:
        return text
    members = getattr(guild, "members", None) or []
    # (tên, id): gom CẢ username, global_name, display_name (tên hiển thị/nick — vd 'ᴊᴀᴄᴋʏ ᴄʜᴜɴ').
    # Ưu tiên tên DÀI trước để khớp đúng cụm dài nhất ('thinh.nguyen2' trước 'thinh').
    idents: list[tuple[str, int]] = []
    for m in members:
        if getattr(m, "id", None) == bot_id:
            continue
        seen: set[str] = set()
        for nm in (
            getattr(m, "name", None),
            getattr(m, "global_name", None),
            getattr(m, "display_name", None),
        ):
            if nm and nm not in seen:
                seen.add(nm)
                idents.append((nm, int(m.id)))
    idents.sort(key=lambda x: len(x[0]), reverse=True)
    for nm, uid in idents:
        if f"<@{uid}>" in text:  # đã có mention ID hợp lệ rồi -> bỏ qua
            continue
        esc = re.escape(nm)
        # (a) Model hay BỊA '<@thinh.nguyen2>' / '<@!thinh.nguyen2>' (nhét tên vào cú pháp mention
        # nhưng Discord cần ID SỐ -> ra chữ trơn). Sửa thành '<@id>' thật.
        text = re.sub(rf"<@!?{esc}>", f"<@{uid}>", text, count=1, flags=re.IGNORECASE)
        if f"<@{uid}>" in text:
            continue
        # (b) Model viết '@Tên' (có @ nhưng KHÔNG phải mention thật -> Discord ra chữ rác có @).
        # @ = ý ĐỊNH tag rõ ràng nên đổi '@Tên' -> '<@id>' kể cả tên không 'đặc trưng' (chỉ cần >=3
        # ký tự, chừa @everyone/@here). Đây chính là ca '@ᴊᴀᴄᴋʏ ᴄʜᴜɴ' (tên hiển thị).
        if len(nm) >= 3 and nm.lower() not in ("everyone", "here"):
            new = re.sub(rf"(?<!\w)@{esc}(?!\w)", f"<@{uid}>", text, count=1, flags=re.IGNORECASE)
            if new != text:
                text = new
                continue
        # (c) Tên CHỮ TRƠN (không @) -> chỉ đổi nếu ĐẶC TRƯNG (tránh ping nhầm từ thường tiếng Việt).
        if _distinctive(nm):
            text = re.sub(
                rf"(?<![\w@<]){esc}(?![\w>])", f"<@{uid}>", text, count=1, flags=re.IGNORECASE
            )
    # PASS CUỐI — dọn MỌI mention BỊA còn sót: '<@...>' / '<@!...>' mà bên trong KHÔNG phải
    # toàn SỐ (Discord chỉ render mention khi là id số). Vd model tự bịa '<@rolt9>' (tên bot) hay
    # '<@tên-lạ>' -> ra chữ rác. Bỏ cặp '<@ >' để lại tên thường. Chừa role '<@&id>' (ký tự '&').
    text = re.sub(r"<@!?([^0-9>&][^>]*)>", r"\1", text)
    return text


def perms_dict(guild_permissions) -> dict:
    """Trích các flag quyền liên quan action thành dict (để gate stage + confirm)."""
    return {f: bool(getattr(guild_permissions, f, False)) for f in _PERM_FLAGS}


def confirm_perm_ok(kind: str, perms: dict) -> bool:
    """Người bấm ✅ có đủ quyền cho action này không (Administrator có sẵn mọi flag)."""
    return bool(perms.get(ACTION_PERMS.get(kind, "")))


class ActionConfirmView(discord.ui.View):
    """Nút ✅/❌ cho hành động PHÁ (ban/kick/timeout/delete_role)."""

    def __init__(self, pending, *, on_resolve=None):
        super().__init__(timeout=120)
        self.pending = pending
        # Gọi khi nút được bấm (✅/❌) -> để cog gỡ khỏi sổ theo dõi 'nút đang chờ',
        # tránh bị 1 lệnh sau ghi đè nhầm lên tin đã xử lý xong.
        self._on_resolve = on_resolve

    def _resolve(self) -> None:
        if self._on_resolve is not None:
            try:
                self._on_resolve()
            except Exception:  # noqa: BLE001 — dọn sổ lỗi không được chặn luồng
                pass

    @discord.ui.button(label="✅ Xác nhận", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not confirm_perm_ok(self.pending.kind, perms_dict(interaction.user.guild_permissions)):
            await interaction.response.send_message(
                "Bạn không đủ quyền cho hành động này.", ephemeral=True
            )
            return
        # Bọc run_action: lỗi (DB/Discord/…) thì BÁO LỖI ngay trên nút, KHÔNG để interaction
        # treo im (trước đây exception ở đây = bấm ✅ xong không có gì xảy ra, người dùng tưởng hỏng).
        try:
            async with session_scope() as session:
                res = await run_action(self.pending, guild=interaction.guild, session=session)
            content = f"✅ {res}"
        except Exception:  # noqa: BLE001 — mọi lỗi đều phải hiện ra cho người bấm, không nuốt
            log.exception("agent confirm: run_action crashed (kind=%s)", self.pending.kind)
            content = "❌ Lỗi khi thực thi hành động này — thử lại sau nhé."
        try:
            await interaction.response.edit_message(content=content, view=None)
        except (DiscordError, discord.DiscordException):
            pass
        self._resolve()
        self.stop()

    @discord.ui.button(label="❌ Hủy", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="Đã hủy.", view=None)
        self._resolve()
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
        # Hàng đợi tin nhắm-bot + pool worker: nhiều người mention CÙNG LÚC sẽ XẾP HÀNG chạy
        # tuần tự (AGENT_WORKERS lượt song song) thay vì drop hoặc đẻ vô số luồng LLM.
        self._queue: asyncio.Queue[discord.Message] = asyncio.Queue(maxsize=AGENT_QUEUE_MAX)
        self._workers: list[asyncio.Task] = []
        # Số lượt mỗi (guild,user) đang chờ/đang chạy -> chặn 1 người nhồi đầy hàng đợi.
        self._pending: dict[tuple[int, int], int] = {}
        # Nút ✅/❌ đang chờ bấm, theo (kênh, loại action, mục tiêu) -> lệnh phá mới CÙNG loại+người
        # sẽ vô hiệu nút cũ (đỡ bấm nhầm giá trị cũ, vd đổi timeout 5p->10p).
        self._pending_confirms: dict[tuple, discord.Message] = {}

    def _ensure_workers(self) -> None:
        """Bảo đảm pool worker đang chạy (idempotent).

        Gọi từ cog_load lúc nạp cog, và phòng hờ ngay đầu on_message — dùng
        asyncio.create_task (loop đang chạy) nên chạy được cả ở runtime lẫn test.
        """
        if self._workers:
            return
        self._workers = [asyncio.create_task(self._worker(i)) for i in range(AGENT_WORKERS)]

    async def cog_load(self) -> None:
        """Khởi động pool worker khi cog được nạp (lúc này đã có event loop)."""
        self._ensure_workers()

    async def cog_unload(self) -> None:
        """Huỷ pool worker khi gỡ/reload cog -> không để task mồ côi chạy nền."""
        for t in self._workers:
            t.cancel()
        self._workers = []

    async def _worker(self, n: int) -> None:
        """Vòng lặp: lấy 1 tin khỏi hàng đợi -> xử lý -> lặp.

        Mỗi worker xử lý 1 lượt agent tại một thời điểm; tổng song song = AGENT_WORKERS.
        Một tin lỗi KHÔNG được giết worker (phải tiếp tục phục vụ người khác trong hàng).
        """
        while True:
            message = await self._queue.get()
            key = (int(message.guild.id), message.author.id)
            try:
                await self._process(message)
            except Exception:  # noqa: BLE001 — nuốt lỗi 1 tin để worker sống tiếp
                log.exception("agent worker %d: _process crashed", n)
            finally:
                # Trả 1 suất pending cho người này + báo hàng đợi xong 1 item.
                remaining = self._pending.get(key, 1) - 1
                if remaining > 0:
                    self._pending[key] = remaining
                else:
                    self._pending.pop(key, None)
                self._queue.task_done()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        if self.bot.user is None or not is_addressed(message, self.bot.user):
            return

        self._ensure_workers()
        now = time.monotonic()
        key = (int(message.guild.id), message.author.id)
        # 3 cửa chống quá tải, xét THEO THỨ TỰ; rớt cửa nào cũng báo ⏳ + log lý do:
        #   1) cooldown : cùng 1 người chỉ kích bot 1 lần / AGENT_COOLDOWN giây (chống spam liên tục).
        #   2) per-user : 1 người chỉ được xếp tối đa AGENT_PER_USER_MAX lượt (chống ôm hàng đợi).
        #   3) full     : hàng đợi đầy (cả server quá tải) -> drop để khỏi phình vô hạn.
        # Qua hết -> XẾP HÀNG; một worker sẽ xử lý tuần tự (không drop tin của người khác).
        if not self.cooldown.ready(*key, now=now):
            await self._throttle(message, "cooldown")
            return
        if self._pending.get(key, 0) >= AGENT_PER_USER_MAX:
            await self._throttle(message, "quá-nhiều-lượt")
            return
        try:
            self._queue.put_nowait(message)
        except asyncio.QueueFull:
            await self._throttle(message, "hàng-đợi-đầy")
            return
        # Vào hàng thành công -> tính cooldown + tăng bộ đếm pending của người này.
        self.cooldown.mark(*key, now=now)
        self._pending[key] = self._pending.get(key, 0) + 1

    async def _throttle(self, message: discord.Message, reason: str) -> None:
        """Báo bị tiết chế bằng reaction ⏳ (nhẹ, KHÔNG đẻ tin nhắn để bot khỏi tự spam) + log lý do."""
        log.info(
            "agent throttle (%s) user=%s guild=%s", reason, message.author.id, message.guild.id
        )
        try:
            await message.add_reaction("⏳")
        except (DiscordError, discord.DiscordException):
            pass

    async def _process(self, message: discord.Message) -> None:
        """Xử lý 1 tin nhắm tới bot (sau khi đã qua slowmode + khoá đang-xử-lý)."""
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
            # owner_id -> để stage từ chối ban/kick/timeout CHỦ SERVER ngay (không hiện nút xác nhận).
            "owner_id": getattr(g, "owner_id", None),
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
                # Lỗi bất ngờ (tool/model crash) -> VẪN báo 1 câu cho người dùng, đừng im luôn
                # (trước đây chỉ log rồi return -> bot lặng thinh, tưởng nuốt lệnh).
                log.exception("agent: respond crashed")
                await self._safe_reply(
                    message, "❌ Mình bị lỗi khi xử lý cái này — thử lại giúp nhé."
                )
                return
            if result is None:
                return

            conversation_id, text, pending = result
            # (cooldown đã mark ở đầu, không mark lại ở đây)

            if pending:
                # LƯỢT HÀNH ĐỘNG: chạy tool TRƯỚC rồi mới báo theo KẾT QUẢ THẬT — KHÔNG gửi lời
                # model (model hay "báo khống đã làm" trước khi tool chạy). Hành động phá -> nút
                # ✅/❌ (chỉ chạy KHI bấm). create_role chạy trước để "tạo role X rồi gán X" chạy được.
                outcomes: list[str] = []
                last_sent = None
                for p in sorted(pending, key=lambda a: 0 if a.kind == "create_role" else 1):
                    if p.destructive:
                        last_sent = await self._send_confirm(message, p) or last_sent
                        # Lưu marker HỆ THỐNG nói RÕ là CHƯA thực hiện -> lượt sau model (a) không nhại
                        # cụm '(chờ admin xác nhận)' như prose, (b) không tưởng hành động đã xong.
                        outcomes.append(
                            f"[hệ thống: mới gửi nút ✅/❌, CHƯA thực hiện] {p.description}"
                        )
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
                # Đổi tên thành viên trong câu -> '<@id>' để bot TAG đúng người (ping), kể cả khi
                # trí nhớ chỉ lưu tên chữ trơn (vd 'thinh.nguyen2' không kèm id lúc được dạy).
                text = tag_known_members(text, message.guild, bot_id)
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

    @staticmethod
    def _confirm_key(channel_id: int, pending) -> tuple:
        """Khoá định danh 1 nút xác nhận theo (kênh, loại action, mục tiêu) — để lệnh phá MỚI
        cùng loại + cùng người vô hiệu nút cũ (vd đổi timeout 5p->10p cho cùng 1 người)."""
        params = getattr(pending, "params", {}) or {}
        tids = params.get("target_ids") or []
        target = (
            tuple(sorted(str(x) for x in tids)) if tids else str(params.get("query", "")).lower()
        )
        return (int(channel_id), pending.kind, target)

    async def _send_confirm(self, message, pending):
        """Gửi nút ✅/❌ cho hành động phá. Nếu đang có nút CŨ cùng (kênh,loại,người) chưa bấm
        -> vô hiệu nó trước (tránh bấm nhầm giá trị cũ). Trả message đã gửi (hoặc None nếu lỗi)."""
        key = self._confirm_key(message.channel.id, pending)
        old = self._pending_confirms.pop(key, None)
        if old is not None:
            try:
                await old.edit(content="⚠️ Đã thay bằng lệnh mới bên dưới.", view=None)
            except (DiscordError, discord.DiscordException):
                pass
        try:
            sent = await message.channel.send(
                f"🤖 Xác nhận hành động: **{pending.description}**?",
                view=ActionConfirmView(
                    pending, on_resolve=lambda: self._pending_confirms.pop(key, None)
                ),
            )
        except (DiscordError, discord.DiscordException):
            log.warning("agent: failed to send confirm in channel %s", message.channel.id)
            return None
        self._pending_confirms[key] = sent
        return sent

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
