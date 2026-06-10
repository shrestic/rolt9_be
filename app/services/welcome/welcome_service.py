"""Welcome plugin facade — build the join/leave message for a guild.

Reads config, renders the template, and (for joins, when `ai_welcome` is on)
asks the AIGateway for a unique greeting — falling back to the rendered template
if AI is disabled / over budget / unconfigured. Returns (channel_id, text) or
None when the plugin is off / no channel set. The cog posts the result.
"""

from app.repositories.guild import GuildRepository
from app.repositories.welcome_config import WelcomeConfigRepository
from app.services.ai.ai_gateway import AIGateway
from app.services.welcome.template import render_template

WELCOME_SYSTEM = (
    "Write ONE welcome sentence for a new member of a Discord server in English: "
    "warm, friendly, short (1 sentence), emoji allowed. Don't make up any information."
)


class WelcomeService:
    def __init__(
        self,
        *,
        guild_repo: GuildRepository,
        config_repo: WelcomeConfigRepository,
        gateway: AIGateway,
    ):
        self.guild_repo = guild_repo
        self.config_repo = config_repo
        self.gateway = gateway

    async def build_welcome(
        self,
        *,
        guild_discord_id: int,
        user_mention: str,
        user_name: str,
        server_name: str,
        member_count: int,
    ) -> tuple[int, str] | None:
        guild = await self.guild_repo.get_by_discord_id(guild_discord_id)
        if guild is None:
            return None
        cfg = await self.config_repo.get(guild.id)
        if cfg is None or not cfg.enabled or cfg.channel_id is None:
            return None
        text = render_template(
            cfg.welcome_template, user=user_mention, server=server_name, count=member_count
        )
        if cfg.ai_welcome:
            try:
                ai = await self.gateway.complete(
                    guild_discord_id=guild_discord_id,
                    system=WELCOME_SYSTEM,
                    prompt=f"Welcome member '{user_name}' who just joined server '{server_name}'.",
                    # Don't set max_tokens -> inherit AI_MAX_TOKENS (200k): a reasoning model (deepseek-v4)
                    # has enough room to finish reasoning before emitting the greeting (a small cap ->
                    # reasoning eats it all -> empty content -> error). The greeting stays SHORT because
                    # WELCOME_SYSTEM forces "1 sentence". On failure -> fall back to the template.
                )
                # Prefix the mention so the new member gets pinged even on the AI line.
                text = f"{user_mention} {ai}"
            except ValueError:
                # AI off / over budget / unconfigured → keep the rendered template.
                pass
        return cfg.channel_id, text

    async def build_leave(
        self,
        *,
        guild_discord_id: int,
        user_name: str,
        server_name: str,
        member_count: int,
    ) -> tuple[int, str] | None:
        guild = await self.guild_repo.get_by_discord_id(guild_discord_id)
        if guild is None:
            return None
        cfg = await self.config_repo.get(guild.id)
        if cfg is None or not cfg.leave_enabled or cfg.channel_id is None:
            return None
        text = render_template(
            cfg.leave_template, user=user_name, server=server_name, count=member_count
        )
        return cfg.channel_id, text
