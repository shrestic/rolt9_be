from types import SimpleNamespace

from app.services.moderation.embeds import build_case_embed


def _case(**kw):
    defaults = {
        "case_number": 1,
        "action": "ban",
        "source": "manual",
        "target_user_id": 7,
        "target_username": "bad#1",
        "moderator_user_id": 8,
        "moderator_username": "mod#1",
        "reason": "spam",
        "duration_seconds": None,
    }
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def test_ban_embed_has_red_color():
    embed = build_case_embed(_case())
    assert embed.color == 0xED4245
    assert "BAN" in embed.title


def test_mute_embed_includes_duration_field():
    embed = build_case_embed(_case(action="mute", duration_seconds=120))
    duration_field = next((f for f in embed.fields if f.name == "Duration"), None)
    assert duration_field is not None
    assert duration_field.value == "120s"


def test_escalation_source_added_as_field():
    embed = build_case_embed(_case(source="escalation"))
    source_field = next((f for f in embed.fields if f.name == "Source"), None)
    assert source_field is not None
    assert source_field.value == "Auto-escalation"


def test_no_reason_uses_default_text():
    embed = build_case_embed(_case(reason=None))
    reason_field = next((f for f in embed.fields if f.name == "Reason"), None)
    assert reason_field is not None
    assert reason_field.value == "No reason given"
