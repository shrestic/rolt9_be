from app.schemas.ai import AISettings, AISettingsOut


def test_defaults():
    s = AISettings()
    assert s.enabled is False
    assert s.monthly_token_budget == 100_000


def test_out_includes_usage():
    o = AISettingsOut(enabled=True, monthly_token_budget=5000, tokens_used_this_month=120)
    assert o.tokens_used_this_month == 120
