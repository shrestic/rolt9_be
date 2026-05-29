import pytest
from pydantic import ValidationError

from app.schemas.currency import CurrencySettings


def test_defaults():
    s = CurrencySettings()
    assert s.enabled is False
    assert s.currency_name == "coins"
    assert s.earn_min == 1 and s.earn_max == 3
    assert s.daily_amount == 100
    assert s.allow_pay is True


def test_rejects_min_gt_max():
    with pytest.raises(ValidationError):
        CurrencySettings(earn_min=5, earn_max=2)


def test_rejects_out_of_range():
    with pytest.raises(ValidationError):
        CurrencySettings(earn_max=10_001)
    with pytest.raises(ValidationError):
        CurrencySettings(daily_amount=-1)
    with pytest.raises(ValidationError):
        CurrencySettings(currency_name="")


def test_currency_settings_accepts_streak_fields():
    s = CurrencySettings(streak_enabled=False, streak_bonus_per_day=25, streak_bonus_cap=1000)
    assert s.streak_enabled is False
    assert s.streak_bonus_per_day == 25
    assert s.streak_bonus_cap == 1000


def test_currency_settings_streak_defaults():
    s = CurrencySettings()
    assert s.streak_enabled is True
    assert s.streak_bonus_per_day == 10
    assert s.streak_bonus_cap == 500
