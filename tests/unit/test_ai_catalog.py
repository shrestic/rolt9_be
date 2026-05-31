from app.services.ai.catalog import AI_CATALOG, is_valid


def test_catalog_has_four_providers():
    assert set(AI_CATALOG) == {"anthropic", "openai", "gemini", "groq"}
    # Mỗi provider có label + danh sách model không rỗng.
    for prov in AI_CATALOG.values():
        assert prov["label"]
        assert len(prov["models"]) >= 1


def test_is_valid_accepts_known_pair():
    assert is_valid("anthropic", "claude-haiku-4-5") is True
    assert is_valid("openai", "gpt-4o-mini") is True


def test_is_valid_rejects_unknown():
    assert is_valid("anthropic", "gpt-4o") is False  # model sai provider
    assert is_valid("nope", "claude-haiku-4-5") is False
    assert is_valid("", "") is False
