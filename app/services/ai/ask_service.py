"""Knowledge Q&A — answer a question from the guild's knowledge base via AIGateway.

v1 is context-stuffing: all of the guild's KB entries are concatenated into the
prompt (capped) and Claude is told to answer ONLY from them. No embeddings/RAG.
Reads KB via `KbRepository`; the gateway owns enable/key/budget. The guild UUID is
resolved by the gateway (from the snowflake), so here we resolve it once via the
guild repo to fetch KB.
"""

from app.repositories.guild import GuildRepository
from app.repositories.kb import KbRepository
from app.services.ai.ai_gateway import AIGateway

KB_CHAR_CAP = 6000  # keep the stuffed context small to bound token cost

ASK_SYSTEM = (
    "Bạn là trợ lý hỏi-đáp của một server Discord. Chỉ trả lời DỰA TRÊN kho tri "
    "thức được cung cấp bên dưới. Nếu câu hỏi không nằm trong kho, hãy nói thẳng "
    "'Mình chưa có thông tin về vấn đề này.' Trả lời tiếng Việt, ngắn gọn, không bịa."
)


class AskService:
    def __init__(self, *, gateway: AIGateway, guild_repo: GuildRepository, kb_repo: KbRepository):
        self.gateway = gateway
        self.guild_repo = guild_repo
        self.kb_repo = kb_repo

    async def ask(self, *, guild_discord_id: int, question: str) -> str:
        guild = await self.guild_repo.get_by_discord_id(guild_discord_id)
        if guild is None:
            raise ValueError("Server chưa đăng ký với bot.")
        entries = await self.kb_repo.list_for_guild(guild.id)
        if not entries:
            raise ValueError("Server chưa có kho tri thức nào — admin thêm ở dashboard nhé.")
        kb = "\n\n".join(f"## {e.title}\n{e.content}" for e in entries)[:KB_CHAR_CAP]
        prompt = f"KHO TRI THỨC:\n{kb}\n\n---\nCÂU HỎI: {question}"
        return await self.gateway.complete(
            guild_discord_id=guild_discord_id,
            system=ASK_SYSTEM,
            prompt=prompt,
            # Không set max_tokens -> kế thừa AI_MAX_TOKENS (200k) cho reasoning model; độ dài câu trả lời do prompt bound.
        )
