from types import SimpleNamespace

import pytest

from app.bot.cache.guild_config_cache import CachedCommand, GuildConfig
from app.bot.cogs.custom_commands import handle_message
from tests.fakes.discord import FakeDiscordClient


def _msg(content, *, channel_id=10, author_id=1, role_ids=()):
    author = SimpleNamespace(
        id=author_id,
        bot=False,
        display_name="Alice",
        mention="<@1>",
        roles=[SimpleNamespace(id=r) for r in role_ids],
    )
    guild = SimpleNamespace(id=100, name="S", member_count=5)
    channel = SimpleNamespace(id=channel_id)
    return SimpleNamespace(content=content, author=author, guild=guild, channel=channel)


def _cmd(**kw):
    defaults = {
        "id": "c1",
        "trigger": "rules",
        "response_type": "text",
        "response_text": "Hi {user}",
        "embed": None,
        "allowed_role_ids": [],
        "allowed_channel_ids": [],
        "cooldown_seconds": 0,
    }
    defaults.update(kw)
    return CachedCommand(**defaults)


def _cfg(commands, prefix="!", enabled=True):
    return GuildConfig(prefix=prefix, enabled=enabled, commands=commands, moderation={})


@pytest.mark.asyncio
async def test_known_trigger_replies_rendered_text():
    m = _msg("!rules")
    discord = FakeDiscordClient()
    assert await handle_message(m, discord, _cfg([_cmd()]), {}) is True
    assert discord.posted_messages == [(10, None, "Hi Alice")]


@pytest.mark.asyncio
async def test_unknown_trigger_ignored():
    m = _msg("!nope")
    discord = FakeDiscordClient()
    assert await handle_message(m, discord, _cfg([_cmd()]), {}) is False
    assert discord.posted_messages == []


@pytest.mark.asyncio
async def test_wrong_prefix_ignored():
    m = _msg("?rules")
    assert await handle_message(m, FakeDiscordClient(), _cfg([_cmd()]), {}) is False


@pytest.mark.asyncio
async def test_channel_restriction_blocks():
    m = _msg("!rules", channel_id=10)
    assert (
        await handle_message(m, FakeDiscordClient(), _cfg([_cmd(allowed_channel_ids=[99])]), {})
        is False
    )


@pytest.mark.asyncio
async def test_role_restriction_allows_member_with_role():
    m = _msg("!rules", role_ids=(5,))
    assert (
        await handle_message(m, FakeDiscordClient(), _cfg([_cmd(allowed_role_ids=[5])]), {}) is True
    )


@pytest.mark.asyncio
async def test_cooldown_blocks_second_use():
    cd: dict = {}
    discord = FakeDiscordClient()
    assert (
        await handle_message(
            _msg("!rules"), discord, _cfg([_cmd(cooldown_seconds=10)]), cd, now=100.0
        )
        is True
    )
    assert (
        await handle_message(
            _msg("!rules"), discord, _cfg([_cmd(cooldown_seconds=10)]), cd, now=105.0
        )
        is False
    )
    assert (
        await handle_message(
            _msg("!rules"), discord, _cfg([_cmd(cooldown_seconds=10)]), cd, now=120.0
        )
        is True
    )


@pytest.mark.asyncio
async def test_disabled_config_ignored():
    assert (
        await handle_message(_msg("!rules"), FakeDiscordClient(), _cfg([_cmd()], enabled=False), {})
        is False
    )


@pytest.mark.asyncio
async def test_embed_command_sends_embed():
    m = _msg("!info")
    cmd = _cmd(
        trigger="info",
        response_type="embed",
        response_text=None,
        embed={"title": "T {server}", "description": "D", "color": "#5865F2"},
    )
    discord = FakeDiscordClient()
    assert await handle_message(m, discord, _cfg([cmd]), {}) is True
    assert len(discord.posted_messages) == 1
    channel_id, embed, content = discord.posted_messages[0]
    assert channel_id == 10
    assert embed is not None
    assert embed.title == "T S"
    assert content is None


@pytest.mark.asyncio
async def test_embed_invalid_color_falls_back_to_default():
    # Admin entered garbage in the color field — instead of crashing the
    # command, we fall back to Discord blurple so the rest of the embed
    # still posts.
    m = _msg("!broken")
    cmd = _cmd(
        trigger="broken",
        response_type="embed",
        response_text=None,
        embed={"title": "T", "description": "D", "color": "not-a-hex"},
    )
    discord = FakeDiscordClient()
    assert await handle_message(m, discord, _cfg([cmd]), {}) is True
    assert len(discord.posted_messages) == 1
    _, embed, _ = discord.posted_messages[0]
    assert embed.color == 0x5865F2  # blurple default
