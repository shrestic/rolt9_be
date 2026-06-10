from app.services.ai.catalog import AI_CATALOG, is_valid


def test_catalog_has_expected_providers():
    # Provider whitelist (including DeepSeek — cheap). Each has a label + non-empty models.
    assert {"anthropic", "openai", "gemini", "deepseek", "groq", "mistral", "xai"} <= set(
        AI_CATALOG
    )
    for prov in AI_CATALOG.values():
        assert prov["label"]
        assert len(prov["models"]) >= 1


def test_is_valid_accepts_known_pair():
    assert is_valid("anthropic", "claude-haiku-4-5") is True
    assert is_valid("openai", "gpt-5.4-mini") is True
    assert is_valid("deepseek", "deepseek-v4-flash") is True


def test_is_valid_rejects_unknown():
    assert is_valid("anthropic", "gpt-5.5") is False  # model from the wrong provider
    assert is_valid("nope", "claude-haiku-4-5") is False
    assert is_valid("", "") is False
