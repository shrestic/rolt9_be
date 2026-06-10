"""Subscription digest — pure (testable) logic for the daily digest subscription.

`is_due` decides 'is it time to post for today yet'; `build_digest_system` builds the
prompt for the AI to summarize web search results into a tidy digest. The I/O (web
search, calling the AI, sending) lives in the cog.
"""

from datetime import datetime

_DEFAULT_DIGEST_PERSONA = (
    "You are an assistant that summarizes news briefly and clearly in English."
)


def is_due(sub, now_vn: datetime) -> bool:
    """True if this subscription is due to post for TODAY and hasn't posted yet.
    Triggers on the beat: at or past the HH:MM time of day + hasn't run today (last_run_on != today)."""
    if sub.last_run_on == now_vn.date():
        return False  # already posted today
    return (now_vn.hour, now_vn.minute) >= (sub.hour, sub.minute)


def build_digest_system(persona: str, topic: str) -> str:
    """Prompt for the AI to summarize web search RESULTS about `topic` into a short digest."""
    base = persona or _DEFAULT_DIGEST_PERSONA
    return (
        base
        + f"\n\nBelow are the WEB SEARCH RESULTS on the topic '{topic}'. Summarize them into a "
        "SHORT digest in English: 1 opening sentence saying what the news is, then 3-5 bullet points with "
        "the key points/figures. Cite sources if worthwhile. NO making stuff up, NO junk links, no rambling."
    )
