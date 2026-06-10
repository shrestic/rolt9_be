from decimal import Decimal

from app.schemas.ai import AISettings, AISettingsOut


def test_defaults():
    s = AISettings()
    assert s.enabled is False
    assert s.provider == ""
    assert s.model == ""
    assert s.monthly_budget_usd == Decimal("5")
    assert s.api_key is None  # write-only, None = leave unchanged


def test_out_shape_hides_key():
    o = AISettingsOut(
        enabled=True,
        provider="openai",
        model="gpt-4o-mini",
        monthly_budget_usd=Decimal("12"),
        persona="",
        agent_enabled=False,
        tools_enabled=True,
        actions_enabled=False,
        companion_enabled=False,
        companion_cooldown_min=45,
        has_key=True,
        key_hint="sk-x"[-4:],
        tokens_used_this_month=120,
        cost_used_this_month=Decimal("0.34"),
    )
    assert o.has_key is True
    assert o.key_hint == "sk-x"
    assert o.cost_used_this_month == Decimal("0.34")
    assert not hasattr(o, "api_key")  # never expose the key
