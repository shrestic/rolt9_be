"""AI Roast — generate a playful roast of a member via the AIGateway.

A thin consumer of the gateway (which owns the enable/key/budget checks). The
system prompt keeps it light and explicitly forbids genuinely hurtful content.
"""

from app.services.ai.ai_gateway import AIGateway

ROAST_SYSTEM = (
    "You are a fun Discord bot that specializes in roasting members in "
    "English. Funny, cheeky, lightly sassy. ABSOLUTELY NO insulting "
    "looks, gender, ethnicity, religion, or family; no heavy profanity. "
    "Answer in 1–2 really short sentences, with charm."
)


class RoastService:
    def __init__(self, *, gateway: AIGateway):
        self.gateway = gateway

    async def roast(self, *, guild_discord_id: int, target_name: str) -> str:
        prompt = f"Drop one really cheeky roast about the member named '{target_name}'."
        return await self.gateway.complete(
            guild_discord_id=guild_discord_id,
            system=ROAST_SYSTEM,
            prompt=prompt,
            # Don't set max_tokens -> inherit AI_MAX_TOKENS (200k) for the reasoning model; the roast stays short thanks to the prompt.
        )
