import pytest
from pydantic import ValidationError

from app.schemas.minigame import MinigameSettings


def test_defaults():
    s = MinigameSettings()
    assert s.enabled is False
    assert s.min_bet == 10
    assert s.max_bet == 10_000


def test_rejects_min_above_max():
    with pytest.raises(ValidationError):
        MinigameSettings(min_bet=5000, max_bet=100)
