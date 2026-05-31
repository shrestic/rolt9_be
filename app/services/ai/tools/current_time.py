"""Tool current_time — giờ/ngày UTC."""

from datetime import UTC, datetime


def run_current_time(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).strftime("%Y-%m-%d %H:%M UTC")
