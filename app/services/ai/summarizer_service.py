"""Chat Summarizer — summarise a channel transcript via the AIGateway.

Thin consumer of the gateway (which owns enable/key/budget). The cog is
responsible for fetching channel history and building the transcript string;
this service stays Discord-agnostic (transcript in → summary out) so it's
unit-testable with a FakeAIProvider.
"""

from app.services.ai.ai_gateway import AIGateway

SUMMARY_SYSTEM = (
    "Bạn là trợ lý tóm tắt hội thoại Discord bằng tiếng Việt. Tóm tắt ngắn gọn, "
    "rõ ràng các ý chính / chủ đề / quyết định trong đoạn chat dưới dạng 3–6 gạch "
    "đầu dòng. Bỏ qua chuyện tầm phào không quan trọng. Không bịa thông tin."
)


class SummarizerService:
    def __init__(self, *, gateway: AIGateway):
        self.gateway = gateway

    async def summarize(self, *, guild_discord_id: int, transcript: str) -> str:
        prompt = f"Tóm tắt đoạn chat sau:\n\n{transcript}"
        return await self.gateway.complete(
            guild_discord_id=guild_discord_id,
            system=SUMMARY_SYSTEM,
            prompt=prompt,
            max_tokens=4096,  # room cho model reasoning (v4) + bản tóm tắt; prompt bound độ dài
        )
