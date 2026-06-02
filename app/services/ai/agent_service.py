"""AgentService — lõi Claw Agent: dựng ngữ cảnh, gọi AI đa lượt, lưu lượt, rút facts.

Cog (AgentCog) lo phần Discord (mention/reply, cooldown, gửi tin); service lo logic
+ DB + gọi gateway. Mọi call AI đi qua AIGateway (budget USD + token/cost).
"""

import re
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.repositories.agent_message import AgentMessageRepository
from app.repositories.ai_config import AIConfigRepository
from app.repositories.guild import GuildRepository
from app.repositories.memory_doc import MemoryDocRepository
from app.repositories.reminder import ReminderRepository
from app.repositories.subscription import SubscriptionRepository
from app.repositories.user_memory import UserMemoryRepository
from app.services.ai.ai_gateway import AIGateway
from app.services.ai.tools.registry import ToolContext
from app.services.ai.tools.runner import run_with_tools

DEFAULT_PERSONA = "Bạn là trợ lý thân thiện, trả lời ngắn gọn, tự nhiên bằng tiếng Việt."

_VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")  # giờ VN để model tính thời điểm đặt nhắc

TURN_LIMIT = 20
HISTORY_CHAR_CAP = 6000
FACTS_CHAR_CAP = 1500
MAX_FACTS = 15

# Khi user nhắn tiếp mà KHÔNG reply: nếu vừa nói trong cùng (kênh, người) trong khoảng
# này thì nối tiếp cuộc cũ cho tự nhiên; im lặng lâu hơn -> coi như cuộc mới. Reply vẫn
# luôn được ưu tiên trên cơ chế này (xem `respond`).
CONVERSATION_WINDOW = timedelta(minutes=20)

# Nhắc model CHỦ ĐỘNG dùng tool/hành động thay vì chỉ trả lời chay — kéo tỉ lệ
# gọi tool lên rõ (kể cả model yếu). Chỉ tool nào được cấp mới gọi được.
_TOOL_NUDGE = (
    "Bạn CÓ công cụ: tra web, xem thông tin server, xem giờ, đặt nhắc (báo thức) / xem / sửa / huỷ nhắc, "
    "đăng ký nhận tin định kỳ hằng ngày / sửa / ngừng đăng ký, tạo poll bình chọn & xoá poll, "
    "và (nếu được cấp) thực hiện hành động trên server — "
    "tạo/gán/gỡ/xóa role, kick/ban/unban thành viên, timeout (mute) và untimeout (unmute/gỡ mute), "
    "bật/tắt plugin. "
    "CHỈ gọi tool khi người dùng THỰC SỰ yêu cầu việc đó. Chào hỏi / tám vu vơ / hỏi thăm "
    "(vd 'alo', 'ê rolt9', 'hello mày', 'rolt9 ơi', 'khỏe ko', 'yo') -> TRẢ LỜI THẲNG bằng lời, "
    "TUYỆT ĐỐI đừng gọi tool nào (đừng web_search, đừng current_time, đừng remember...). "
    "Khi người dùng YÊU CẦU một hành động, HÃY GỌI THẲNG đúng tool hành động đó — "
    "ĐỪNG gọi server_info để 'kiểm tra' trước; hệ thống tự xác thực role/thành viên khi bạn gọi tool "
    "và sẽ báo lại nếu sai, nên cứ gọi tool hành động luôn. "
    "Người được nhắc (@) trong tin là mục tiêu của hành động. "
    "Khi unban, người bị ban đã rời server nên KHÔNG @ được — hãy truyền tên/ID họ vào tham số 'user'. "
    "DÙ tính cách của bạn có cà khịa/bựa tới đâu, khi được yêu cầu một hành động bạn BẮT BUỘC gọi tool "
    "(muốn chọc ghẹo thì nói thêm SAU khi đã gọi tool) — không được chỉ chửi/đùa rồi thôi mà quên làm. "
    "Với hành động phá (xóa role, kick, ban, timeout): ĐỪNG hỏi lại 'có chắc không?' bằng lời — "
    "cứ gọi tool, hệ thống sẽ TỰ hiện nút ✅/❌ cho admin xác nhận. "
    "TỐI QUAN TRỌNG — CẤM NÓI KHỐNG: TUYỆT ĐỐI không được nói 'đã gỡ/đã mute/đã ban/đã kick/đã gán/"
    "đã tha/đã xong...' nếu trong lượt này bạn CHƯA thực sự gọi tool tương ứng. Muốn làm gì thì PHẢI "
    "gọi tool đó trước; chưa gọi thì đừng báo thành công. Câu mềm như 'tha cho nó', 'cho nó thoát', "
    "'thả nó ra' = YÊU CẦU HÀNH ĐỘNG -> gọi tool (vd untimeout/unban), không phải chỉ tám. "
    "ĐỪNG SUY ĐOÁN TRẠNG THÁI: bạn KHÔNG biết chắc ai đang bị ban/đã kick/đã rời/đang mute — "
    "kể cả hội thoại trước có nhắc tới (lệnh cũ có thể đã huỷ/thất bại). Khi được yêu cầu kick/ban/"
    "mute/gỡ ai, TUYỆT ĐỐI đừng từ chối hay bịa kiểu 'nó bị ban rồi, kick gì nữa' — cứ GỌI THẲNG tool, "
    "hệ thống kiểm tra thật và báo lại (vd 'không kick được chủ server', 'không tìm thấy', 'role cao hơn'). "
    "ĐỪNG NHẠI CÂU HỆ THỐNG: các cụm trong LỊCH SỬ như '(chờ admin xác nhận)...', 'Timeout 1 người X phút', "
    "'Đã ban/kick/timeout...' là do HỆ THỐNG sinh ra, KHÔNG phải mẫu để bạn copy. TUYỆT ĐỐI đừng tự gõ "
    "'(chờ admin xác nhận)' hay tự mô tả hành động như đã làm — muốn timeout/ban/kick/mute ai thì CHỈ việc "
    "GỌI TOOL, hệ thống tự lo nút ✅/❌ + câu thông báo. Đổi ý ('thôi 1p thôi') = GỌI LẠI tool với số mới. "
    "TAG NGƯỜI: khi NHẮC TỚI một người mà bạn biết '<@id>' của họ (ở mục 'Người được @' hoặc trong "
    "'TRÍ NHỚ SERVER'), HÃY viết nguyên cụm '<@id>' để tag thật — ĐỪNG viết tên/biệt danh trơn "
    "(vd biết loz Khôi = <@123> thì viết '<@123>', không viết 'loz Khôi'). "
    "QUAN TRỌNG: '<@...>' CHỈ hợp lệ khi bên trong là ID SỐ (vd <@123456>). TUYỆT ĐỐI ĐỪNG bịa "
    "'<@tên>'/'<@username>' (vd <@thinh.nguyen2>) — Discord không tag được, ra chữ rác. Nếu chỉ "
    "biết TÊN mà không có id số, cứ viết TÊN THƯỜNG (vd 'thinh.nguyen2'), hệ thống sẽ tự tag giúp."
)

# Quy tắc độ dài — đặt CUỐI system prompt (vị trí model bám nhất) và nói rõ ưu tiên
# hơn cá tính, nếu không persona bựa sẽ lấn át làm bot trả lời lan man, nhảm.
_STYLE_GUIDE = (
    "QUY TẮC TRẢ LỜI (quan trọng hơn cá tính, BẮT BUỘC tuân theo):\n"
    "- Mặc định trả lời 1 câu, cụt lủn, đúng trọng tâm — như nhắn tin chứ không phải viết văn.\n"
    "- KHI VỪA LÀM XONG việc qua công cụ (đặt nhắc, tạo poll, gán/gỡ role, kick/ban, bật/tắt...): "
    "CHỈ xác nhận NGẮN 1 câu, vd 'Ok 7h tối tao nhắc mày', 'Poll xong, vào vote đi'. Muốn cà khịa thì "
    "gói GỌN trong đúng câu đó — CẤM thêm vế sau kể lể, suy diễn, lên lớp, đá đưa chuyện khác.\n"
    "- CẤM mở bài/dẫn dắt lan man, CẤM lặp ý, CẤM 'kể lể' dài dòng vô ích. Thà cụt còn hơn nhảm.\n"
    "- Chỉ viết dài hơn khi người ta THẬT SỰ hỏi điều cần giải thích chi tiết (hướng dẫn, lý do)."
)

_EXTRACT_SYSTEM = (
    "Bạn là bộ lọc trí nhớ. Dưới đây là facts đã biết về user + một lượt trao đổi mới. "
    "Trả về danh sách facts BỀN VỮNG, đáng nhớ về user (tên, sở thích, vai trò, điều họ "
    "muốn bạn nhớ), gộp với cũ, bỏ trùng, tối đa 15 dòng, mỗi dòng 1 fact ngắn. KHÔNG bịa. "
    "Nếu không có gì mới đáng nhớ, trả lại nguyên facts cũ. Chỉ in danh sách, mỗi fact một "
    "dòng, không thêm chữ nào khác."
)


def build_system(
    persona: str,
    facts: str,
    user_name: str,
    memory_doc: str = "",
    channel_context: str = "",
    now_text: str = "",
    mention_map: str = "",
) -> str:
    """Ghép persona + trí nhớ server (memory_doc) + facts về user + ngữ cảnh kênh
    thành system prompt. memory_doc là lore chung toàn server (biệt danh, luật, …) áp
    cho MỌI lượt; channel_context là vài tin nhắn gần đây trong kênh để bot bám sát hội thoại.
    now_text = giờ VN hiện tại để model tính thời điểm khi đặt nhắc (tool remind).
    mention_map = ánh xạ 'tên -> <@id>' của người được @ trong tin, để model TAG thật + ghi nhớ kèm id."""
    base = persona or DEFAULT_PERSONA
    parts = [base, _TOOL_NUDGE, f"\nBạn đang nói chuyện với '{user_name}'."]
    if now_text:
        parts.append(f"\nBây giờ (giờ VN): {now_text}.")
    if mention_map.strip():
        # Tên -> <@id>: để khi GHI NHỚ hoặc NHẮC TỚI một người, model tag thật bằng <@id>
        # (vd nhớ '<@123> biệt danh loz Khôi'), sau này gọi đúng người chứ không phải chữ trơn.
        parts.append(
            f"\nNgười được @ trong tin (DÙNG NGUYÊN cụm <@id> này để tag/ghi nhớ họ): {mention_map.strip()}"
        )
    if memory_doc.strip():
        # Lore toàn server — luôn tuân theo (vd: "từ nay gọi An là X").
        # Nếu trong này có dạng <@số>, khi nhắc tới người đó hãy DÙNG <@số> để tag thật.
        parts.append(f"\nTRÍ NHỚ SERVER (luôn áp dụng):\n{memory_doc.strip()}")
    if facts.strip():
        parts.append(f"\nNhững điều bạn nhớ về người này:\n{facts.strip()}")
    if channel_context.strip():
        # Tin gần đây trong kênh để bám sát cuộc trò chuyện đang diễn ra.
        parts.append(f"\nVài tin nhắn gần đây trong kênh:\n{channel_context.strip()}")
    # Quy tắc độ dài để CUỐI cùng -> model bám sát nhất, chống lan man.
    parts.append(f"\n{_STYLE_GUIDE}")
    return "\n".join(parts)


# Cụm trong ngoặc kép (mọi kiểu nháy) — biệt danh người dùng tự đặt thường được lưu dạng này.
_NICK_QUOTE_RE = re.compile(r"[\"'“”‘’«»]([^\"'“”‘’«»\n]{2,40})[\"'“”‘’«»]")


def extract_nick_mentions(memory_doc: str) -> list[tuple[str, int]]:
    """Rút (biệt danh -> user id) từ TRÍ NHỚ SERVER để sau này tag thật.

    Quy ước an toàn: chỉ nhận DÒNG có ĐÚNG 1 '<@id>' — khi đó mọi cụm trong ngoặc kép trên
    dòng đó coi là biệt danh của người ấy (vd '<@945> (Jacky) có biệt danh "ngọc gà"').
    Dòng có nhiều id / không id -> bỏ (tránh map nhầm người).
    """
    out: list[tuple[str, int]] = []
    for line in (memory_doc or "").splitlines():
        ids = re.findall(r"<@!?(\d+)>", line)
        if len(set(ids)) != 1:
            continue
        uid = int(ids[0])
        for nick in _NICK_QUOTE_RE.findall(line):
            nick = nick.strip()
            if nick:
                out.append((nick, uid))
    return out


def apply_nick_mentions(text: str, memory_doc: str) -> str:
    """Đổi biệt danh tự đặt (vd 'ngọc gà', '@ngọc gà') trong câu trả lời thành '<@id>' để LUÔN
    tag thật người đó — kể cả khi model chỉ viết biệt danh trơn. Ưu tiên biệt danh DÀI trước."""
    if not text or not memory_doc:
        return text
    # KHÔNG bỏ qua theo uid: 1 người có thể có NHIỀU biệt danh ('ngọc gà' lẫn 'ngọc kem') cùng
    # xuất hiện -> phải tag HẾT, đừng skip chỉ vì đã tag 1 biệt danh khác của họ. Ưu tiên biệt
    # danh DÀI trước để khớp đúng cụm dài nhất; mỗi biệt danh đổi MỌI lần xuất hiện.
    for nick, uid in sorted(
        extract_nick_mentions(memory_doc), key=lambda x: len(x[0]), reverse=True
    ):
        # '@ngọc gà' hoặc 'ngọc gà' (chữ trơn) ở ranh giới từ -> '<@id>'.
        text = re.sub(rf"(?<!\w)@?{re.escape(nick)}(?!\w)", f"<@{uid}>", text, flags=re.IGNORECASE)
    return text


class AgentService:
    def __init__(
        self,
        *,
        guild_repo: GuildRepository,
        config_repo: AIConfigRepository,
        agent_msg_repo: AgentMessageRepository,
        memory_repo: UserMemoryRepository,
        memory_doc_repo: MemoryDocRepository,
        reminder_repo: ReminderRepository,
        subscription_repo: SubscriptionRepository,
        gateway: AIGateway,
    ):
        self.guild_repo = guild_repo
        self.config_repo = config_repo
        self.agent_msg_repo = agent_msg_repo
        self.memory_repo = memory_repo
        self.memory_doc_repo = memory_doc_repo
        self.reminder_repo = reminder_repo
        self.subscription_repo = subscription_repo
        self.gateway = gateway

    async def _guild_pk(self, guild_discord_id: int) -> uuid.UUID:
        guild = await self.guild_repo.get_by_discord_id(guild_discord_id)
        if guild is None:
            raise ValueError("Server chưa đăng ký với bot.")
        return guild.id

    async def respond(
        self,
        *,
        guild_discord_id: int,
        channel_id: int,
        user_discord_id: int,
        user_name: str,
        message_text: str,
        reference_message_id: int | None,
        server_snapshot: dict | None = None,
        commander_perms: dict | None = None,
        role_names: list[str] | None = None,
        target_user_ids: list[int] | None = None,
        commander_id: int | None = None,
        channel_context: str = "",
        mention_map: str = "",
    ) -> tuple[uuid.UUID, str, list] | None:
        """Gating + chọn conversation + gọi AI. Trả (conversation_id, text, pending_actions),
        hoặc None nếu agent không nên trả lời. Lỗi cấu hình AI raise ValueError để cog báo ❌."""
        guild = await self.guild_repo.get_by_discord_id(guild_discord_id)
        if guild is None:
            return None
        cfg = await self.config_repo.get(guild.id)
        if cfg is None or not cfg.enabled or not cfg.agent_enabled:
            return None
        if cfg.agent_channel_id and channel_id != cfg.agent_channel_id:
            return None

        # Chọn cuộc theo 3 tầng ưu tiên:
        #   1) User REPLY vào tin bot -> nối đúng cuộc đó (rõ ràng nhất).
        #   2) Không reply, nhưng vừa nói trong cùng (kênh, người) gần đây -> nối cuộc
        #      gần nhất (tự nhiên, đỡ bắt user phải reply).
        #   3) Còn lại -> cuộc mới.
        conversation_id = None
        if reference_message_id is not None:
            conversation_id = await self.agent_msg_repo.conversation_of(reference_message_id)
        if conversation_id is None:
            conversation_id = await self.agent_msg_repo.latest_conversation(
                guild.id,
                channel_id=channel_id,
                user_discord_id=user_discord_id,
                within=CONVERSATION_WINDOW,
                now=datetime.now(UTC),
            )
        if conversation_id is None:
            conversation_id = uuid.uuid4()

        facts = await self.memory_repo.get_facts(guild.id, user_discord_id)
        memory_doc = await self.memory_doc_repo.get_doc(guild.id)
        history = await self.agent_msg_repo.recent_turns(
            conversation_id, limit=TURN_LIMIT, char_cap=HISTORY_CHAR_CAP
        )
        # Giờ VN hiện tại để model tính thời điểm khi đặt nhắc ("ngày mai 5h30" -> tuyệt đối).
        now_text = datetime.now(_VN_TZ).strftime("%Y-%m-%d %H:%M (%A)")
        system = build_system(
            cfg.persona, facts, user_name, memory_doc, channel_context, now_text, mention_map
        )

        perms = commander_perms or {}
        can_act = any(perms.values())
        include_actions = bool(cfg.actions_enabled) and can_act
        ctx = ToolContext(
            guild_snapshot=server_snapshot,
            can_act=can_act,
            role_names=role_names or [],
            target_user_ids=target_user_ids or [],
            commander_id=commander_id,
            commander_perms=perms,
            guild_discord_id=guild_discord_id,
            # Tool `remember` LUÔN có — ghi vào trí nhớ server qua repo này.
            memory_repo_doc=self.memory_doc_repo,
            guild_pk=guild.id,
            # Tool `remind` — ghi báo thức; channel_id = kênh sẽ nhắc khi tới giờ.
            reminder_repo=self.reminder_repo,
            channel_id=channel_id,
            # Tool `subscribe`/`unsubscribe`/`list_subscriptions` — đăng ký tin định kỳ.
            subscription_repo=self.subscription_repo,
        )

        # Luôn đi qua tool-loop: tool `remember` luôn sẵn sàng nên không còn nhánh "chat chay".
        text = await run_with_tools(
            gateway=self.gateway,
            guild_discord_id=guild_discord_id,
            system=system,
            history=history,
            user_text=message_text,
            ctx=ctx,
            has_search=cfg.tools_enabled and bool(settings.TAVILY_API_KEY),
            include_actions=include_actions,
        )
        # Biệt danh tự đặt ('ngọc gà'…) trong câu -> '<@id>' để LUÔN tag thật người đó.
        text = apply_nick_mentions(text, memory_doc)
        return conversation_id, text, ctx.pending

    async def remember(
        self,
        *,
        guild_discord_id: int,
        conversation_id: uuid.UUID,
        user_discord_id: int,
        user_text: str,
        assistant_text: str,
        bot_message_id: int,
        channel_id: int | None = None,
    ) -> None:
        """Sau khi đã gửi reply: lưu 2 lượt + async rút facts. Lỗi rút facts không chặn."""
        guild = await self.guild_repo.get_by_discord_id(guild_discord_id)
        if guild is None:
            return
        old_facts = await self.memory_repo.get_facts(guild.id, user_discord_id)
        await self.persist(
            guild.id,
            conversation_id,
            user_text,
            assistant_text,
            bot_message_id,
            channel_id=channel_id,
            user_discord_id=user_discord_id,
        )
        await self.extract_memory(
            guild_discord_id, user_discord_id, user_text, assistant_text, old_facts
        )

    async def persist(
        self,
        guild_id: uuid.UUID,
        conversation_id: uuid.UUID,
        user_text: str,
        assistant_text: str,
        bot_message_id: int,
        channel_id: int | None = None,
        user_discord_id: int | None = None,
    ) -> None:
        # Gắn (kênh, người) vào CẢ 2 lượt -> sau này `latest_conversation` tra ra được
        # cuộc này khi user nhắn tiếp mà không reply.
        await self.agent_msg_repo.add_turn(
            guild_id,
            conversation_id,
            "user",
            user_text,
            channel_id=channel_id,
            user_discord_id=user_discord_id,
        )
        await self.agent_msg_repo.add_turn(
            guild_id,
            conversation_id,
            "assistant",
            assistant_text,
            discord_message_id=bot_message_id,
            channel_id=channel_id,
            user_discord_id=user_discord_id,
        )

    async def extract_memory(
        self,
        guild_discord_id: int,
        user_discord_id: int,
        user_text: str,
        assistant_text: str,
        old_facts: str,
    ) -> None:
        """Rút facts mới (qua gateway) rồi upsert. Lỗi/rỗng -> bỏ qua (không raise)."""
        gid = await self._guild_pk(guild_discord_id)
        prompt = f"FACTS CŨ:\n{old_facts}\n\n---\nUSER: {user_text}\nBOT: {assistant_text}"
        try:
            out = await self.gateway.complete(
                guild_discord_id=guild_discord_id, system=_EXTRACT_SYSTEM, prompt=prompt
            )
        except Exception:  # noqa: BLE001 — rút facts là phụ, không được làm hỏng luồng
            return
        lines = [ln.strip() for ln in out.splitlines() if ln.strip()][:MAX_FACTS]
        facts = "\n".join(lines)[:FACTS_CHAR_CAP]
        if facts:
            await self.memory_repo.upsert_facts(gid, user_discord_id, facts)
