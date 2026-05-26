from app.services.custom_command_service import (
    is_allowed,
    is_on_cooldown,
    render_template,
)


def test_render_replaces_known_placeholders():
    out = render_template(
        "Hi {user}, welcome to {server}! ({member_count} members)",
        {"user": "Alice", "server": "MyServer", "member_count": "42"},
    )
    assert out == "Hi Alice, welcome to MyServer! (42 members)"


def test_render_leaves_unknown_placeholders_untouched():
    assert render_template("{user} {nope}", {"user": "A"}) == "A {nope}"


def test_render_user_and_user_mention_do_not_collide():
    out = render_template("{user.mention} is {user}", {"user": "Bob", "user.mention": "<@1>"})
    assert out == "<@1> is Bob"


def test_is_allowed_empty_lists_allow_everyone_everywhere():
    assert (
        is_allowed(member_role_ids={1}, channel_id=9, allowed_role_ids=[], allowed_channel_ids=[])
        is True
    )


def test_is_allowed_role_restriction():
    assert (
        is_allowed(
            member_role_ids={2}, channel_id=9, allowed_role_ids=[2, 3], allowed_channel_ids=[]
        )
        is True
    )
    assert (
        is_allowed(
            member_role_ids={5}, channel_id=9, allowed_role_ids=[2, 3], allowed_channel_ids=[]
        )
        is False
    )


def test_is_allowed_channel_restriction():
    assert (
        is_allowed(member_role_ids={2}, channel_id=9, allowed_role_ids=[], allowed_channel_ids=[9])
        is True
    )
    assert (
        is_allowed(member_role_ids={2}, channel_id=8, allowed_role_ids=[], allowed_channel_ids=[9])
        is False
    )


def test_cooldown():
    assert is_on_cooldown(last_used=None, cooldown_seconds=10, now=100.0) is False
    assert is_on_cooldown(last_used=95.0, cooldown_seconds=10, now=100.0) is True
    assert is_on_cooldown(last_used=80.0, cooldown_seconds=10, now=100.0) is False
    assert is_on_cooldown(last_used=95.0, cooldown_seconds=0, now=100.0) is False
