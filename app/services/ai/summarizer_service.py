"""Chat Summarizer — summarise a channel transcript via the AIGateway.

Thin consumer of the gateway (which owns enable/key/budget). The cog is
responsible for fetching channel history and building the transcript string;
this service stays Discord-agnostic (transcript in → summary out) so it's
unit-testable with a FakeAIProvider.
"""

from app.services.ai.ai_gateway import AIGateway

SUMMARY_SYSTEM = (
    "You are an assistant that summarizes Discord conversations in English. Summarize "
    "the main points / topics / decisions in the chat clearly and briefly as 3–6 bullet "
    "points. Skip the unimportant small talk. Don't make up information."
)


class SummarizerService:
    def __init__(self, *, gateway: AIGateway):
        self.gateway = gateway

    async def summarize(self, *, guild_discord_id: int, transcript: str) -> str:
        prompt = f"Summarize the following chat:\n\n{transcript}"
        return await self.gateway.complete(
            guild_discord_id=guild_discord_id,
            system=SUMMARY_SYSTEM,
            prompt=prompt,
            # Don't set max_tokens -> inherit AI_MAX_TOKENS (200k) for the reasoning model; summary length is bounded by the prompt.
        )
