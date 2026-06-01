from app.services.ai.reminder_service import build_reminder_task_system


def test_build_reminder_task_system_includes_persona_and_task():
    s = build_reminder_task_system("rolt9 vui tính", "giá vàng hôm nay")
    assert "rolt9 vui tính" in s  # giữ giọng guild
    assert "giá vàng hôm nay" in s  # nêu rõ việc cần tra


def test_build_reminder_task_system_default_persona_when_blank():
    s = build_reminder_task_system("", "thời tiết Hà Nội")
    assert "rolt9" in s.lower()  # persona mặc định
    assert "thời tiết Hà Nội" in s


def test_build_reminder_task_system_warns_against_fabricating():
    # Prompt phải dặn ĐỪNG bịa số khi web không rõ.
    s = build_reminder_task_system("x", "tỷ giá USD")
    assert "bịa" in s.lower()
