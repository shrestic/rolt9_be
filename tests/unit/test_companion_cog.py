import contextlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

import app.bot.cogs.companion as companion_mod
from app.bot.cogs.companion import CompanionCog

# Fixed timestamp for the test (cooldown is now measured against the real UTC clock, stored in DB).
NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)


class _AsyncIter:
    def __init__(self, items):
        self._items = items

    def __aiter__(self):
        async def gen():
            for x in self._items:
                yield x

        return gen()


def _channel(history_items=()):
    return SimpleNamespace(
        id=10, send=AsyncMock(), history=lambda limit: _AsyncIter(list(history_items))
    )


def _member(name, game=None):
    acts = [SimpleNamespace(type=discord.ActivityType.playing, name=game)] if game else []
    return SimpleNamespace(id=hash(name) % 9999, bot=False, display_name=name, activities=acts)


def _guild(channel, members=()):
    return SimpleNamespace(
        id=100, get_channel=lambda cid: channel, members=list(members), voice_channels=[]
    )


def _cfg(**kw):
    base = {
        "enabled": True,
        "companion_enabled": True,
        "companion_channel_id": 10,
        "companion_cooldown_min": 45,
        "companion_last_post_at": None,  # never posted yet (cooldown doesn't block)
        "persona": "",
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _patch(monkeypatch, stub):
    """Patch session_scope + _build_service + MemoryDocRepository + AIConfigRepository.
    Returns a cfg_repo mock so tests can assert set_companion_last_post (writes the cooldown mark to DB)."""

    @contextlib.asynccontextmanager
    async def fake_scope():
        yield MagicMock()

    monkeypatch.setattr(companion_mod, "session_scope", fake_scope)
    monkeypatch.setattr(companion_mod, "_build_service", lambda session: stub)
    doc_repo = MagicMock()
    doc_repo.get_doc = AsyncMock(return_value="")
    monkeypatch.setattr(companion_mod, "MemoryDocRepository", lambda session: doc_repo)
    cfg_repo = MagicMock()
    cfg_repo.set_companion_last_post = AsyncMock()
    monkeypatch.setattr(companion_mod, "AIConfigRepository", lambda session: cfg_repo)
    return cfg_repo


def _cog(cfg):
    bot = MagicMock()
    bot.user = SimpleNamespace(id=1)
    cog = CompanionCog(bot, MagicMock())
    # _load_cfg returns (guild_row, cfg); guild_row.id is used to load memory_doc + write the cooldown mark
    cog._load_cfg = AsyncMock(return_value=(SimpleNamespace(id="gpk"), cfg))
    return cog


@pytest.mark.asyncio
async def test_handle_guild_posts_when_activity(monkeypatch):
    stub = MagicMock()
    stub.decide = AsyncMock(return_value="Yo An's playing LoL solo huh 👀")
    cfg_repo = _patch(monkeypatch, stub)
    cog = _cog(_cfg())
    ch = _channel()
    guild = _guild(ch, members=[_member("An", game="LoL")])
    await cog._handle_guild(guild, now=NOW)
    stub.decide.assert_awaited_once()
    ch.send.assert_awaited_once()
    # after posting -> write the cooldown mark to DB (survives a restart)
    cfg_repo.set_companion_last_post.assert_awaited_once_with("gpk", NOW)


@pytest.mark.asyncio
async def test_companion_tick_skips_first_run_after_restart():
    # tasks.loop runs the first iteration RIGHT when online -> must SKIP so the bot doesn't speak up every restart.
    cog = _cog(_cfg())
    cog._handle_guild = AsyncMock()
    cog.bot.guilds = [SimpleNamespace(id=100)]
    await cog.companion_tick()  # first iteration (just restarted) -> skip
    cog._handle_guild.assert_not_awaited()
    await cog.companion_tick()  # next iteration (one cycle elapsed) -> runs normally
    cog._handle_guild.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_guild_skip_when_disabled(monkeypatch):
    stub = MagicMock()
    stub.decide = AsyncMock()
    _patch(monkeypatch, stub)
    cog = _cog(_cfg(companion_enabled=False))
    ch = _channel()
    await cog._handle_guild(_guild(ch, members=[_member("An", game="LoL")]), now=NOW)
    stub.decide.assert_not_awaited()
    ch.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_guild_skip_no_activity(monkeypatch):
    stub = MagicMock()
    stub.decide = AsyncMock()
    _patch(monkeypatch, stub)
    cog = _cog(_cfg())
    ch = _channel()  # no history, no members -> snapshot None
    await cog._handle_guild(_guild(ch, members=[]), now=NOW)
    stub.decide.assert_not_awaited()  # DON'T call the AI when there's nothing


@pytest.mark.asyncio
async def test_handle_guild_cooldown_blocks(monkeypatch):
    stub = MagicMock()
    stub.decide = AsyncMock(return_value="hi")
    _patch(monkeypatch, stub)
    # posted 60s ago, cooldown 45' -> still blocked
    cog = _cog(_cfg(companion_cooldown_min=45, companion_last_post_at=NOW - timedelta(seconds=60)))
    ch = _channel()
    await cog._handle_guild(_guild(ch, members=[_member("An", game="LoL")]), now=NOW)
    stub.decide.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_guild_cooldown_survives_restart(monkeypatch):
    # BUG GUARD: cooldown is read from DB (cfg), NOT RAM -> a restart (brand-new cog) still remembers.
    stub = MagicMock()
    stub.decide = AsyncMock(return_value="hi")
    _patch(monkeypatch, stub)
    cfg = _cfg(companion_cooldown_min=45, companion_last_post_at=NOW - timedelta(minutes=5))
    cog = _cog(cfg)  # 'new cog' simulating after a restart, no RAM state
    ch = _channel()
    await cog._handle_guild(_guild(ch, members=[_member("An", game="LoL")]), now=NOW)
    stub.decide.assert_not_awaited()  # 5' < 45' -> stays quiet even right after a restart


@pytest.mark.asyncio
async def test_handle_guild_skip_silenced(monkeypatch):
    stub = MagicMock()
    stub.decide = AsyncMock(return_value=None)  # AI chose SKIP
    cfg_repo = _patch(monkeypatch, stub)
    cog = _cog(_cfg())
    ch = _channel()
    await cog._handle_guild(_guild(ch, members=[_member("An", game="LoL")]), now=NOW)
    ch.send.assert_not_awaited()
    cfg_repo.set_companion_last_post.assert_not_awaited()  # didn't post -> don't set cooldown


# ---------- real-time: on_presence_update (just started a game) ----------


def _pmember(guild, game=None, name="An", uid=1):
    """Member for a presence event: has .guild + .mention + activities."""
    acts = [SimpleNamespace(type=discord.ActivityType.playing, name=game)] if game else []
    return SimpleNamespace(
        id=uid, bot=False, display_name=name, mention=f"<@{uid}>", activities=acts, guild=guild
    )


@pytest.mark.asyncio
async def test_presence_event_posts_when_game_started(monkeypatch):
    stub = MagicMock()
    stub.decide = AsyncMock(return_value="Yo <@1> playing Valorant solo, anyone wanna carry")
    cfg_repo = _patch(monkeypatch, stub)
    cog = _cog(_cfg())
    ch = _channel()
    member = _pmember(None, game="Valorant")
    guild = _guild(ch, members=[member])
    await cog._handle_presence_event(guild, member, ["Valorant"], now=NOW)
    stub.decide.assert_awaited_once()
    ch.send.assert_awaited_once()
    cfg_repo.set_companion_last_post.assert_awaited_once_with("gpk", NOW)
    snap = stub.decide.call_args.kwargs["snapshot"]
    assert (
        "JUST NOW" in snap and "Valorant" in snap
    )  # snapshot spells out the just-started-game event


@pytest.mark.asyncio
async def test_presence_event_skip_when_disabled(monkeypatch):
    stub = MagicMock()
    stub.decide = AsyncMock()
    _patch(monkeypatch, stub)
    cog = _cog(_cfg(companion_enabled=False))
    member = _pmember(None, game="Valorant")
    await cog._handle_presence_event(_guild(_channel(), [member]), member, ["Valorant"], now=NOW)
    stub.decide.assert_not_awaited()


@pytest.mark.asyncio
async def test_presence_event_respects_cooldown(monkeypatch):
    stub = MagicMock()
    stub.decide = AsyncMock(return_value="hi")
    _patch(monkeypatch, stub)
    # spoke 60s ago, cooldown 5' -> still blocked
    cog = _cog(_cfg(companion_cooldown_min=5, companion_last_post_at=NOW - timedelta(seconds=60)))
    member = _pmember(None, game="Valorant")
    await cog._handle_presence_event(_guild(_channel(), [member]), member, ["Valorant"], now=NOW)
    stub.decide.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_presence_update_fires_only_on_new_game(monkeypatch):
    cog = _cog(_cfg())
    cog._handle_presence_event = AsyncMock()
    g = SimpleNamespace(id=100)
    # not playing -> just started Valorant: MUST fire
    await cog.on_presence_update(_pmember(g), _pmember(g, game="Valorant"))
    cog._handle_presence_event.assert_awaited_once()
    # already playing Valorant, presence changed for another reason: DON'T fire
    cog._handle_presence_event.reset_mock()
    await cog.on_presence_update(_pmember(g, game="Valorant"), _pmember(g, game="Valorant"))
    cog._handle_presence_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_presence_update_announces_game_once_per_session(monkeypatch):
    # Playing one game -> announce only ONCE. A later presence flap (same game) does NOT re-announce.
    cog = _cog(_cfg())
    cog._handle_presence_event = AsyncMock()
    g = SimpleNamespace(id=100)
    before = _pmember(g)  # not playing
    after = _pmember(g, game="Valorant")  # just opened Valorant
    await cog.on_presence_update(before, after)
    cog._handle_presence_event.assert_awaited_once()  # announced once
    # presence flap: still on Valorant, 'before' drops the game for a beat then 'after' has it again -> DON'T re-announce
    cog._handle_presence_event.reset_mock()
    await cog.on_presence_update(_pmember(g), after)
    cog._handle_presence_event.assert_not_awaited()  # same game still playing -> stay quiet


@pytest.mark.asyncio
async def test_on_presence_update_reannounces_after_game_ends(monkeypatch):
    # Close the game then reopen = a new session -> ALLOWED to re-announce.
    cog = _cog(_cfg())
    cog._handle_presence_event = AsyncMock()
    g = SimpleNamespace(id=100)
    after = _pmember(g, game="Valorant")
    await cog.on_presence_update(_pmember(g), after)
    cog._handle_presence_event.assert_awaited_once()
    # close Valorant: presence updates to 'playing nothing' -> the 'announced' marker is cleared
    cog._handle_presence_event.reset_mock()
    await cog.on_presence_update(
        after, _pmember(g)
    )  # ended (doesn't fire since there's no new game)
    # open Valorant again -> new session -> re-announce
    await cog.on_presence_update(_pmember(g), _pmember(g, game="Valorant"))
    cog._handle_presence_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_on_presence_update_ignores_bots(monkeypatch):
    cog = _cog(_cfg())
    cog._handle_presence_event = AsyncMock()
    g = SimpleNamespace(id=100)
    bot_after = _pmember(g, game="Valorant")
    bot_after.bot = True
    await cog.on_presence_update(_pmember(g), bot_after)
    cog._handle_presence_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_decide_and_post_strips_self_mention(monkeypatch):
    # the model accidentally tags the bot itself -> must be stripped before sending
    stub = MagicMock()
    stub.decide = AsyncMock(return_value="Yo <@1> come play, <@777> I'm in too")
    _patch(monkeypatch, stub)
    cog = _cog(_cfg())
    cog.bot.user = SimpleNamespace(id=777)  # the bot is 777
    ch = _channel()
    member = _pmember(None, game="Valorant", uid=1)
    await cog._handle_presence_event(_guild(ch, [member]), member, ["playing Valorant"], now=NOW)
    sent = ch.send.call_args.args[0]
    assert "<@777>" not in sent  # the bot mention was stripped
    assert "<@1>" in sent  # the other person's mention remains
