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


def test_next_streak_within_window_increments():
    last = NOW - timedelta(hours=30)
    assert next_streak(last, NOW, 5) == 6


def test_next_streak_exactly_48h_still_counts():
    last = NOW - timedelta(hours=48)
    assert next_streak(last, NOW, 5) == 6


def test_next_streak_beyond_window_resets():
    last = NOW - timedelta(hours=49)
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
