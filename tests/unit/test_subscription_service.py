from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.services.ai.subscription_service import build_digest_system, is_due

VN = ZoneInfo("Asia/Ho_Chi_Minh")


def _sub(hour, minute=0, last_run_on=None):
    return SimpleNamespace(hour=hour, minute=minute, last_run_on=last_run_on)


def test_is_due_true_when_time_passed_and_not_run_today():
    now = datetime(2026, 6, 1, 9, 0, tzinfo=VN)
    assert is_due(_sub(8, 0), now) is True


def test_is_due_false_before_scheduled_time():
    now = datetime(2026, 6, 1, 7, 0, tzinfo=VN)
    assert is_due(_sub(8, 0), now) is False


def test_is_due_false_when_already_ran_today():
    now = datetime(2026, 6, 1, 9, 0, tzinfo=VN)
    assert is_due(_sub(8, 0, last_run_on=date(2026, 6, 1)), now) is False


def test_is_due_true_next_day_after_prior_run():
    now = datetime(2026, 6, 2, 8, 0, tzinfo=VN)
    assert is_due(_sub(8, 0, last_run_on=date(2026, 6, 1)), now) is True


def test_build_digest_system_includes_topic():
    s = build_digest_system("You are a bot.", "stock news")
    assert "stock news" in s and "WEB SEARCH" in s
