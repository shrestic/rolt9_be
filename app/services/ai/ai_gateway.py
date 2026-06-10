"""AIGateway — the single door every AI feature calls through.

Controls cost BEFORE spending money: the guild must have AI enabled, must have an API key +
provider + model (BYO-key, NO global key fallback), and the USD cost for the current UTC month
must be under budget. After that it decrypts the key, calls the provider, then records tokens + cost.
The repo flushes; the caller's session-scope commits.
"""

from datetime import UTC, datetime

from app.core.config import settings
from app.core.crypto import decrypt_str
from app.repositories.ai_config import AIConfigRepository
from app.repositories.ai_usage import AIUsageRepository
from app.repositories.guild import GuildRepository
from app.services.ai.provider import AIProvider


def month_key(now: datetime) -> str:
    """UTC year-month key, e.g. '2026-05' — the budget reset cycle."""
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
        history: list[dict] | None = None,
        now: datetime | None = None,
    ) -> str:
        guild = await self.guild_repo.get_by_discord_id(guild_discord_id)
        if guild is None:
            raise ValueError("Server isn't registered with the bot yet.")
        cfg = await self.config_repo.get(guild.id)
        if cfg is None or not cfg.enabled:
            raise ValueError("AI isn't enabled on this server yet.")
        # BYO-key: missing key/provider/model => AI counts as unconfigured (no global fallback).
        if cfg.api_key_enc is None or not cfg.provider or not cfg.model:
            raise ValueError(
                "AI isn't configured yet — head to the dashboard, enter an API key and pick a model."
            )
        # USD cost guardrail.
        pk = month_key(now or datetime.now(UTC))
        spent = await self.usage_repo.cost_this_period(guild.id, pk)
        if spent >= cfg.monthly_budget_usd:
            raise ValueError(
                "Out of AI budget for this month — bump the budget or wait til next month."
            )
        api_key = decrypt_str(cfg.api_key_enc)
        result = await self.provider.complete(
            provider=cfg.provider,
            model=cfg.model,
            api_key=api_key,
            system=system,
            prompt=prompt,
            max_tokens=max_tokens or settings.AI_MAX_TOKENS,
            history=history,
        )
        await self.usage_repo.add_usage(
            guild.id,
            pk,
            tokens=result.input_tokens + result.output_tokens,
            cost_usd=result.cost_usd,
        )
        if not result.text:
            raise ValueError("Model returned empty content.")
        return result.text

    async def complete_raw(
        self,
        *,
        guild_discord_id: int,
        messages: list[dict],
        tools: list[dict] | None = None,
        max_tokens: int | None = None,
        now: datetime | None = None,
    ):
        """One step of the tool-calling loop: same guard (enabled/key/budget) + usage logging,
        but takes `messages` (including tool results) + `tools`, returns the raw AICompletion
        (text or tool_calls). The loop itself lives in ToolRunner."""
        guild = await self.guild_repo.get_by_discord_id(guild_discord_id)
        if guild is None:
            raise ValueError("Server isn't registered with the bot yet.")
        cfg = await self.config_repo.get(guild.id)
        if cfg is None or not cfg.enabled:
            raise ValueError("AI isn't enabled on this server yet.")
        if cfg.api_key_enc is None or not cfg.provider or not cfg.model:
            raise ValueError(
                "AI isn't configured yet — head to the dashboard, enter an API key and pick a model."
            )
        pk = month_key(now or datetime.now(UTC))
        spent = await self.usage_repo.cost_this_period(guild.id, pk)
        if spent >= cfg.monthly_budget_usd:
            raise ValueError(
                "Out of AI budget for this month — bump the budget or wait til next month."
            )
        api_key = decrypt_str(cfg.api_key_enc)
        result = await self.provider.complete(
            provider=cfg.provider,
            model=cfg.model,
            api_key=api_key,
            system="",
            prompt="",
            messages=messages,
            tools=tools,
            max_tokens=max_tokens or settings.AI_MAX_TOKENS,
            # Tool-calling loop: if a reasoning model runs out of tokens -> return text="" so ToolRunner
            # degrades gracefully ("give it another go"), instead of throwing a technical error at the user.
            allow_empty=True,
        )
        await self.usage_repo.add_usage(
            guild.id,
            pk,
            tokens=result.input_tokens + result.output_tokens,
            cost_usd=result.cost_usd,
        )
        return result
