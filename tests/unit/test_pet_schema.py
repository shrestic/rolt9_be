import pytest
from pydantic import ValidationError

from app.schemas.pet import PetSettings


def test_defaults():
    s = PetSettings()
    assert s.enabled is False
    assert s.name == "Pet"
    assert s.feed_cost == 10
    assert s.decay_per_day == 20


def test_rejects_empty_name():
    with pytest.raises(ValidationError):
        PetSettings(name="")


def test_rejects_zero_feed_amount():
    with pytest.raises(ValidationError):
        PetSettings(feed_amount=0)
