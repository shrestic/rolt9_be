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
    "You are the Q&A assistant for a Discord server. Answer ONLY BASED ON the "
    "knowledge base provided below. If the question isn't covered by it, just say "
    "straight up 'I don't have any info on this yet.' Answer in English, keep it short, no making stuff up."
)


class AskService:
    def __init__(self, *, gateway: AIGateway, guild_repo: GuildRepository, kb_repo: KbRepository):
        self.gateway = gateway
        self.guild_repo = guild_repo
        self.kb_repo = kb_repo

    async def ask(self, *, guild_discord_id: int, question: str) -> str:
        guild = await self.guild_repo.get_by_discord_id(guild_discord_id)
        if guild is None:
            raise ValueError("This server hasn't registered with the bot yet.")
        entries = await self.kb_repo.list_for_guild(guild.id)
        if not entries:
            raise ValueError(
                "This server has no knowledge base yet — admin, add some in the dashboard."
            )
        kb = "\n\n".join(f"## {e.title}\n{e.content}" for e in entries)[:KB_CHAR_CAP]
        prompt = f"KNOWLEDGE BASE:\n{kb}\n\n---\nQUESTION: {question}"
        return await self.gateway.complete(
            guild_discord_id=guild_discord_id,
            system=ASK_SYSTEM,
            prompt=prompt,
            # Don't set max_tokens -> inherit AI_MAX_TOKENS (200k) for the reasoning model; answer length is bounded by the prompt.
        )
