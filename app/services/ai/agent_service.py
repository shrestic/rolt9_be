"""AgentService — lõi Claw Agent: dựng ngữ cảnh, gọi AI đa lượt, lưu lượt, rút facts.

Cog (AgentCog) lo phần Discord (mention/reply, cooldown, gửi tin); service lo logic
+ DB + gọi gateway. Mọi call AI đi qua AIGateway (budget USD + token/cost).
"""

import uuid

from app.core.config import settings
from app.repositories.agent_message import AgentMessageRepository
from app.repositories.ai_config import AIConfigRepository
from app.repositories.guild import GuildRepository
from app.repositories.user_memory import UserMemoryRepository
from app.services.ai.ai_gateway import AIGateway
from app.services.ai.tools.registry import ToolContext
from app.services.ai.tools.runner import run_with_tools

DEFAULT_PERSONA = "Bạn là trợ lý thân thiện, trả lời ngắn gọn, tự nhiên bằng tiếng Việt."

TURN_LIMIT = 20
HISTORY_CHAR_CAP = 6000
FACTS_CHAR_CAP = 1500
MAX_FACTS = 15

_EXTRACT_SYSTEM = (
    "Bạn là bộ lọc trí nhớ. Dưới đây là facts đã biết về user + một lượt trao đổi mới. "
    "Trả về danh sách facts BỀN VỮNG, đáng nhớ về user (tên, sở thích, vai trò, điều họ "
    "muốn bạn nhớ), gộp với cũ, bỏ trùng, tối đa 15 dòng, mỗi dòng 1 fact ngắn. KHÔNG bịa. "
    "Nếu không có gì mới đáng nhớ, trả lại nguyên facts cũ. Chỉ in danh sách, mỗi fact một "
    "dòng, không thêm chữ nào khác."
)


def build_system(persona: str, facts: str, user_name: str) -> str:
    """Ghép persona + facts nhớ về user thành system prompt cho lượt trả lời."""
    base = persona or DEFAULT_PERSONA
    parts = [base, f"\nBạn đang nói chuyện với '{user_name}'."]
    if facts.strip():
        parts.append(f"\nNhững điều bạn nhớ về người này:\n{facts.strip()}")
    return "\n".join(parts)


class AgentService:
    def __init__(
        self,
        *,
        guild_repo: GuildRepository,
        config_repo: AIConfigRepository,
        agent_msg_repo: AgentMessageRepository,
        memory_repo: UserMemoryRepository,
        gateway: AIGateway,
    ):
        self.guild_repo = guild_repo
        self.config_repo = config_repo
        self.agent_msg_repo = agent_msg_repo
        self.memory_repo = memory_repo
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
    ) -> tuple[uuid.UUID, str] | None:
        """Gating + chọn conversation + gọi AI. Trả (conversation_id, text), hoặc None nếu
        agent không nên trả lời (chưa đăng ký / AI off / agent off / sai kênh). Lỗi cấu hình
        AI (thiếu key / hết budget) raise ValueError để cog báo ❌."""
        guild = await self.guild_repo.get_by_discord_id(guild_discord_id)
        if guild is None:
            return None
        cfg = await self.config_repo.get(guild.id)
        if cfg is None or not cfg.enabled or not cfg.agent_enabled:
            return None
        if cfg.agent_channel_id and channel_id != cfg.agent_channel_id:
            return None

        conversation_id = None
        if reference_message_id is not None:
            conversation_id = await self.agent_msg_repo.conversation_of(reference_message_id)
        if conversation_id is None:
            conversation_id = uuid.uuid4()

        facts = await self.memory_repo.get_facts(guild.id, user_discord_id)
        history = await self.agent_msg_repo.recent_turns(
            conversation_id, limit=TURN_LIMIT, char_cap=HISTORY_CHAR_CAP
        )
        system = build_system(cfg.persona, facts, user_name)
        if cfg.tools_enabled:
            text = await run_with_tools(
                gateway=self.gateway,
                guild_discord_id=guild_discord_id,
                system=system,
                history=history,
                user_text=message_text,
                ctx=ToolContext(guild_snapshot=server_snapshot),
                has_search=bool(settings.TAVILY_API_KEY),
            )
        else:
            text = await self.gateway.complete(
                guild_discord_id=guild_discord_id,
                system=system,
                prompt=message_text,
                history=history,
            )
        return conversation_id, text

    async def remember(
        self,
        *,
        guild_discord_id: int,
        conversation_id: uuid.UUID,
        user_discord_id: int,
        user_text: str,
        assistant_text: str,
        bot_message_id: int,
    ) -> None:
        """Sau khi đã gửi reply: lưu 2 lượt + async rút facts. Lỗi rút facts không chặn."""
        guild = await self.guild_repo.get_by_discord_id(guild_discord_id)
        if guild is None:
            return
        old_facts = await self.memory_repo.get_facts(guild.id, user_discord_id)
        await self.persist(guild.id, conversation_id, user_text, assistant_text, bot_message_id)
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
    ) -> None:
        await self.agent_msg_repo.add_turn(guild_id, conversation_id, "user", user_text)
        await self.agent_msg_repo.add_turn(
            guild_id,
            conversation_id,
            "assistant",
            assistant_text,
            discord_message_id=bot_message_id,
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
