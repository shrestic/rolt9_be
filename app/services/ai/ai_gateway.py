"""AIGateway — cửa duy nhất mọi feature AI gọi qua.

Kiểm soát chi phí TRƯỚC khi tiêu tiền: guild phải bật AI, phải có API key +
provider + model (BYO-key, KHÔNG fallback key global), và chi phí USD tháng UTC
hiện tại phải dưới budget. Sau đó giải mã key, gọi provider, rồi ghi token + cost.
Repo flush; session-scope của caller commit.
"""

from datetime import UTC, datetime

from app.core.config import settings
from app.core.crypto import decrypt_str
from app.repositories.ai_config import AIConfigRepository
from app.repositories.ai_usage import AIUsageRepository
from app.repositories.guild import GuildRepository
from app.services.ai.provider import AIProvider


def month_key(now: datetime) -> str:
    """Khóa năm-tháng UTC, vd '2026-05' — chu kỳ reset budget."""
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
            raise ValueError("Server chưa đăng ký với bot.")
        cfg = await self.config_repo.get(guild.id)
        if cfg is None or not cfg.enabled:
            raise ValueError("AI chưa được bật trên server này.")
        # BYO-key: thiếu key/provider/model => AI coi như chưa cấu hình (no global fallback).
        if cfg.api_key_enc is None or not cfg.provider or not cfg.model:
            raise ValueError("AI chưa được cấu hình — vào dashboard nhập API key và chọn model.")
        # Hàng rào chi phí theo USD.
        pk = month_key(now or datetime.now(UTC))
        spent = await self.usage_repo.cost_this_period(guild.id, pk)
        if spent >= cfg.monthly_budget_usd:
            raise ValueError("Hết ngân sách AI tháng này rồi — tăng budget hoặc đợi tháng sau.")
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
        return result.text
