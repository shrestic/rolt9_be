from datetime import UTC, datetime, timedelta

from app.services.currency.streak import (
    MILESTONES,
    days_to_next_milestone,
    milestone_reward,
    next_streak,
    streak_bonus,
)

NOW = datetime(2026, 5, 29, 12, 0, tzinfo=UTC)


def test_next_streak_first_claim_is_one():
    assert next_streak(None, NOW, 0) == 1


def test_next_streak_claimed_yesterday_increments():
    # Yesterday at any time → consecutive day → +1.
    last = NOW - timedelta(hours=30)  # May 28 06:00 = yesterday (UTC)
    assert next_streak(last, NOW, 5) == 6


def test_next_streak_yesterday_late_still_counts():
    # Even claiming late yesterday (23:00) then early today counts as consecutive,
    # since it compares calendar days, not elapsed hours.
    last = datetime(2026, 5, 28, 23, 0, tzinfo=UTC)
    now = datetime(2026, 5, 29, 1, 0, tzinfo=UTC)  # only 2h later, but next day
    assert next_streak(last, now, 5) == 6


def test_next_streak_same_day_no_change():
    # Same UTC day → no advance (claim guard normally blocks this anyway).
    last = NOW - timedelta(hours=2)  # still May 29
    assert next_streak(last, NOW, 5) == 5


def test_next_streak_skipped_a_day_resets():
    # Two days ago → a full UTC day was skipped → reset to 1.
    last = NOW - timedelta(hours=48)  # May 27 12:00 = 2 days ago
    assert next_streak(last, NOW, 5) == 1


def test_streak_bonus_is_linear_under_cap():
    assert streak_bonus(3, per_day=10, cap=500) == 30


def test_streak_bonus_clamped_at_cap():
    assert streak_bonus(1000, per_day=10, cap=500) == 500


def test_milestone_reward_hits_exact_day():
    assert milestone_reward(7) == 200
    assert milestone_reward(30) == 1000


def test_milestone_reward_zero_between_milestones():
    assert milestone_reward(6) == 0
    assert milestone_reward(8) == 0


def test_days_to_next_milestone():
    assert days_to_next_milestone(3) == 4  # → 7
    assert days_to_next_milestone(7) == 23  # → 30
    assert days_to_next_milestone(max(MILESTONES)) is None
