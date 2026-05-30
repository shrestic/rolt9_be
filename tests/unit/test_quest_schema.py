import pytest
from pydantic import ValidationError

from app.schemas.quests import QuestIn


def test_valid_quest():
    q = QuestIn(
        name="Earn 500", period="daily", objective_type="earn_coins", target=500, reward_coins=100
    )
    assert q.enabled is True
    assert q.description is None


def test_rejects_bad_period():
    with pytest.raises(ValidationError):
        QuestIn(name="x", period="monthly", objective_type="earn_coins", target=1, reward_coins=0)


def test_rejects_bad_objective():
    with pytest.raises(ValidationError):
        QuestIn(name="x", period="daily", objective_type="kill_boss", target=1, reward_coins=0)


def test_rejects_nonpositive_target():
    with pytest.raises(ValidationError):
        QuestIn(name="x", period="daily", objective_type="earn_coins", target=0, reward_coins=0)
