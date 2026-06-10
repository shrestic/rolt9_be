"""Tool current_time — current UTC time/date."""

from datetime import UTC, datetime


def run_current_time(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).strftime("%Y-%m-%d %H:%M UTC")
