from datetime import UTC, datetime, timedelta

from app.services.pet.pet_logic import (
    XP_PER_ACTION,
    mood_for,
    pet_level,
    settle_decay,
    stage_for,
)


def test_pet_level_curve():
    assert pet_level(0) == 1
    assert pet_level(49) == 1
    assert pet_level(50) == 2
    assert pet_level(500) == 11


def test_stage_for_thresholds():
    assert stage_for(1)[1] == "🥚"
    assert stage_for(4)[1] == "🥚"
    assert stage_for(5)[1] == "🐣"
    assert stage_for(14)[1] == "🐣"
    assert stage_for(15)[1] == "🐤"
    assert stage_for(30)[1] == "🦅"
    assert stage_for(99)[1] == "🦅"


def test_mood_buckets():
    assert mood_for(100, 100) == "😸"
    assert mood_for(50, 50) == "🙂"
    assert mood_for(20, 20) == "😟"
    assert mood_for(0, 0) == "😿"


def test_settle_decay_drops_over_time():
    last = datetime(2026, 5, 30, 0, 0, tzinfo=UTC)
    now = last + timedelta(days=1)
    assert settle_decay(100, 100, last, now, 20) == (80, 80)


def test_settle_decay_floors_at_zero():
    last = datetime(2026, 5, 30, 0, 0, tzinfo=UTC)
    now = last + timedelta(days=10)
    assert settle_decay(50, 30, last, now, 20) == (0, 0)


def test_settle_decay_none_anchor_is_noop():
    now = datetime(2026, 5, 30, 0, 0, tzinfo=UTC)
    assert settle_decay(70, 60, None, now, 20) == (70, 60)


def test_xp_per_action_constant():
    assert XP_PER_ACTION == 5
