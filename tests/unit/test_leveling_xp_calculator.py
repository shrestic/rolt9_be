import pytest

from app.services.leveling.xp_calculator import (
    apply_decay,
    level_for_xp,
    total_xp_for_level,
    xp_to_next,
)


def test_xp_to_next_level_zero_costs_100():
    # formula: 5*L^2 + 50*L + 100 → L=0 → 100
    assert xp_to_next(0) == 100


def test_xp_to_next_grows_quadratically():
    assert xp_to_next(1) == 155
    assert xp_to_next(2) == 220
    assert xp_to_next(10) == 1100


def test_total_xp_for_level_zero_is_zero():
    assert total_xp_for_level(0) == 0


def test_total_xp_for_level_one_equals_first_step():
    assert total_xp_for_level(1) == 100


def test_total_xp_for_level_two_sums_first_two_steps():
    assert total_xp_for_level(2) == 100 + 155


@pytest.mark.parametrize(
    "xp, expected_level",
    [
        (0, 0),
        (99, 0),
        (100, 1),
        (254, 1),
        (255, 2),
        (475, 3),
    ],
)
def test_level_for_xp_boundaries(xp, expected_level):
    assert level_for_xp(xp) == expected_level


def test_level_for_xp_handles_very_high_xp():
    # 200 levels worth — should not stack-overflow / hang
    assert level_for_xp(10_000_000) > 50


def test_apply_decay_zero_periods_is_noop():
    assert apply_decay(1000, level_floor=770, percent=10, periods=0) == 1000


def test_apply_decay_negative_periods_is_noop():
    assert apply_decay(1000, level_floor=770, percent=10, periods=-3) == 1000


def test_apply_decay_single_period():
    assert apply_decay(1000, level_floor=770, percent=10, periods=1) == 900


def test_apply_decay_compounds_over_periods():
    assert apply_decay(1000, level_floor=770, percent=10, periods=2) == 810


def test_apply_decay_floors_at_level_threshold():
    assert apply_decay(1000, level_floor=770, percent=10, periods=4) == 770


def test_apply_decay_already_at_floor_stays():
    assert apply_decay(770, level_floor=770, percent=10, periods=5) == 770
