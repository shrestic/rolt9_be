from datetime import UTC, datetime

from app.services.quests.quest_period import (
    OBJECTIVES,
    PERIODS,
    period_key,
)


def test_daily_key_is_utc_date():
    now = datetime(2026, 5, 30, 13, 0, tzinfo=UTC)
    assert period_key("daily", now) == "2026-05-30"


def test_weekly_key_is_iso_week():
    # 2026-05-30 is a Saturday; ISO week 22 of 2026.
    now = datetime(2026, 5, 30, 13, 0, tzinfo=UTC)
    assert period_key("weekly", now) == "2026-W22"


def test_weekly_key_rolls_over_on_monday():
    sunday = datetime(2026, 5, 31, 23, 0, tzinfo=UTC)  # ISO week 22
    monday = datetime(2026, 6, 1, 0, 30, tzinfo=UTC)  # ISO week 23
    assert period_key("weekly", sunday) == "2026-W22"
    assert period_key("weekly", monday) == "2026-W23"


def test_constants_present():
    assert PERIODS == {"daily", "weekly"}
    assert OBJECTIVES == {"earn_coins", "daily_claim"}
