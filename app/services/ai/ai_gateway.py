"""AIGateway — the single chokepoint every AI feature calls.

Enforces the cost controls before spending money: the guild must have AI enabled,
the provider must be configured (API key present), and the guild's token usage
this UTC month must be under its budget. Then it calls the provider and records
the tokens spent. Repos flush; the caller's session scope commits.
"""

from datetime import UTC, datetime

from app.core.config import settings
from app.repositories.ai_config import AIConfigRepository
from app.repositories.ai_usage import AIUsageRepository
from app.repositories.guild import GuildRepository
from app.services.ai.provider import AIProvider


def month_key(now: datetime) -> str:
    """UTC year-month key, e.g. '2026-05' — the budget reset period."""
    return now.strftime("%Y-%m")


class AIGateway:
    def __init__(
        self,
        *,
        guild_repo: GuildRepository,
        config_repo: AIConfigRepository,
        usage_repo: AIUsageRepository,
        provider: AIProvider,
    ):
        self.guild_repo = guild_repo
        self.config_repo = config_repo
        self.usage_repo = usage_repo
        self.provider = provider

    async def complete(
        self,
        *,
        guild_discord_id: int,
        system: str,
        prompt: str,
        max_tokens: int | None = None,
        now: datetime | None = None,
    ) -> str:
        guild = await self.guild_repo.get_by_discord_id(guild_discord_id)
        if guild is None:
            raise ValueError("Server chưa đăng ký với bot.")
        cfg = await self.config_repo.get(guild.id)
        if cfg is None or not cfg.enabled:
            raise ValueError("AI chưa được bật trên server này.")
        if not self.provider.available:
            raise ValueError("AI chưa được cấu hình (thiếu API key).")
        now = now or datetime.now(UTC)
        pk = month_key(now)
        used = await self.usage_repo.tokens_this_period(guild.id, pk)
        if used >= cfg.monthly_token_budget:
            raise ValueError("Hết quota AI của tháng này rồi — thử lại tháng sau nhé.")
        result = await self.provider.complete(
            system=system, prompt=prompt, max_tokens=max_tokens or settings.AI_MAX_TOKENS
        )
        await self.usage_repo.add_tokens(guild.id, pk, result.input_tokens + result.output_tokens)
        return result.text
