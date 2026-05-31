"""AI Personality — chat with the bot in the server's configured persona.

`/chat` uses the guild's `persona` (from guild_ai_config) as the system prompt so
each server's bot has its own voice; an empty persona falls back to a friendly
default. Thin consumer of the AIGateway (enable/key/budget).
"""

from app.repositories.ai_config import AIConfigRepository
from app.repositories.guild import GuildRepository
from app.services.ai.ai_gateway import AIGateway

DEFAULT_PERSONA = (
    "Bạn là một bot Discord thân thiện, vui vẻ và hữu ích. Trả lời ngắn gọn, "
    "tự nhiên bằng tiếng Việt."
)


class ChatService:
    def __init__(
        self, *, gateway: AIGateway, guild_repo: GuildRepository, config_repo: AIConfigRepository
    ):
        self.gateway = gateway
        self.guild_repo = guild_repo
        self.config_repo = config_repo

    async def chat(self, *, guild_discord_id: int, message: str) -> str:
        guild = await self.guild_repo.get_by_discord_id(guild_discord_id)
        if guild is None:
            raise ValueError("Server chưa đăng ký với bot.")
        cfg = await self.config_repo.get(guild.id)
        persona = (cfg.persona if cfg and cfg.persona else "") or DEFAULT_PERSONA
        # Để gateway dùng settings.AI_MAX_TOKENS (đủ rộng cho model reasoning);
        # hardcode 400 trước đây làm model thinking như DeepSeek trả về rỗng.
        return await self.gateway.complete(
            guild_discord_id=guild_discord_id,
            system=persona,
            prompt=message,
        )
