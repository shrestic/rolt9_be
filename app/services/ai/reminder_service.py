"""Reminder service — prompt for the "smart reminder" (split out from the cog so it's testable).

When a reminder has a `task`, at the scheduled time the scheduler searches the web
(run_web_search) and asks the AI to give a REAL answer based on those results.
`build_reminder_task_system` builds the system prompt for this AI step: answer
straight to the point, with concrete figures, kept short.
"""

# Default persona if the guild hasn't set one — keeps the bot's voice, avoids dry answers.
_DEFAULT_PERSONA = "You are rolt9 — a Discord assistant, talking naturally and straight-shooting."


def build_reminder_task_system(persona: str, task: str) -> str:
    """System prompt for the AI turn that answers a smart reminder.

    persona = the guild's bot voice (empty -> default). task = what the user asked
    to look up (e.g. 'gold price today'). The user prompt will be the raw web search RESULTS.
    """
    base = (persona or "").strip() or _DEFAULT_PERSONA
    return (
        f"{base}\n"
        f"The user SCHEDULED you to look this up and report at this time: '{task}'. "
        "Below are the latest web search RESULTS. Answer STRAIGHT to the point in English, "
        "SHORT, WITH concrete FIGURES/DETAILS if available (price, timestamps, source). "
        "If the results aren't clear enough, just say you're not sure — DON'T make up numbers."
    )
