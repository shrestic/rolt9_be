"""AI Roast — generate a playful Vietnamese roast of a member via the AIGateway.

A thin consumer of the gateway (which owns the enable/key/budget checks). The
system prompt keeps it light and explicitly forbids genuinely hurtful content.
"""

from app.services.ai.ai_gateway import AIGateway

ROAST_SYSTEM = (
    "Bạn là một bot Discord vui tính chuyên 'cà khịa' (roast) thành viên bằng "
    "tiếng Việt. Hài hước, lầy lội, châm biếm nhẹ nhàng. TUYỆT ĐỐI KHÔNG xúc phạm "
    "ngoại hình, giới tính, sắc tộc, tôn giáo, gia đình; không dùng từ tục tĩu nặng. "
    "Trả lời 1–2 câu thật ngắn, có duyên."
)


class RoastService:
    def __init__(self, *, gateway: AIGateway):
        self.gateway = gateway

    async def roast(self, *, guild_discord_id: int, target_name: str) -> str:
        prompt = f"Cà khịa một câu thật lầy về thành viên tên '{target_name}'."
        return await self.gateway.complete(
            guild_discord_id=guild_discord_id,
            system=ROAST_SYSTEM,
            prompt=prompt,
            # Không set max_tokens -> kế thừa AI_MAX_TOKENS (200k) cho reasoning model; câu roast vẫn ngắn nhờ prompt.
        )
