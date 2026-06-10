from app.services.ai.reminder_service import build_reminder_task_system


def test_build_reminder_task_system_includes_persona_and_task():
    s = build_reminder_task_system("rolt9 funny", "gold price today")
    assert "rolt9 funny" in s  # keeps the guild's voice
    assert "gold price today" in s  # spells out what to look up


def test_build_reminder_task_system_default_persona_when_blank():
    s = build_reminder_task_system("", "Hanoi weather")
    assert "rolt9" in s.lower()  # default persona
    assert "Hanoi weather" in s


def test_build_reminder_task_system_warns_against_fabricating():
    # The prompt must instruct NOT to make up numbers when the web results are unclear.
    s = build_reminder_task_system("x", "USD exchange rate")
    assert "make up" in s.lower()
