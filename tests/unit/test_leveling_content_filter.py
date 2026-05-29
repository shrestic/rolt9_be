from app.services.leveling.content_filter import FilterConfig, should_award


def cfg(**overrides):
    base = {
        "min_message_length": 4,
        "ignore_emoji_only": True,
        "ignore_link_only": True,
    }
    base.update(overrides)
    return FilterConfig(**base)


def test_award_for_normal_message():
    assert should_award("hello everyone", cfg()) is True


def test_reject_too_short():
    assert should_award("hi", cfg()) is False
    assert should_award("ok ", cfg()) is False  # whitespace stripped


def test_min_length_configurable_off():
    assert should_award("hi", cfg(min_message_length=1)) is True


def test_reject_emoji_only():
    assert should_award("😀😀😀", cfg()) is False
    assert should_award("👍", cfg()) is False


def test_emoji_with_text_is_allowed():
    assert should_award("hello 👋 there", cfg()) is True


def test_reject_custom_discord_emoji_only():
    # Discord custom emoji: <:name:1234> or <a:name:1234>
    assert should_award("<:smile:123456>", cfg()) is False
    assert should_award("<a:wave:987654>", cfg()) is False


def test_emoji_only_filter_can_be_off():
    assert should_award("😀😀😀😀", cfg(ignore_emoji_only=False)) is True


def test_reject_link_only():
    assert should_award("https://example.com", cfg()) is False
    assert should_award("http://x.io/", cfg()) is False


def test_link_with_text_is_allowed():
    assert should_award("check https://example.com out", cfg()) is True


def test_link_only_filter_can_be_off():
    assert should_award("https://example.com", cfg(ignore_link_only=False)) is True
