import contextlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

import app.bot.cogs.companion as companion_mod
from app.bot.cogs.companion import CompanionCog

# Mốc thời gian cố định cho test (cooldown giờ tính theo đồng hồ thực UTC, lưu DB).
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
        "companion_last_post_at": None,  # chưa post lần nào (cooldown không chặn)
        "persona": "",
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _patch(monkeypatch, stub):
    """Patch session_scope + _build_service + MemoryDocRepository + AIConfigRepository.
    Trả cfg_repo mock để test assert set_companion_last_post (ghi mốc cooldown vào DB)."""

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
    # _load_cfg trả (guild_row, cfg); guild_row.id dùng để nạp memory_doc + ghi mốc cooldown
    cog._load_cfg = AsyncMock(return_value=(SimpleNamespace(id="gpk"), cfg))
    return cog


@pytest.mark.asyncio
async def test_handle_guild_posts_when_activity(monkeypatch):
    stub = MagicMock()
    stub.decide = AsyncMock(return_value="Ê An chơi LoL một mình kìa 👀")
    cfg_repo = _patch(monkeypatch, stub)
    cog = _cog(_cfg())
    ch = _channel()
    guild = _guild(ch, members=[_member("An", game="LoL")])
    await cog._handle_guild(guild, now=NOW)
    stub.decide.assert_awaited_once()
    ch.send.assert_awaited_once()
    # post xong -> ghi mốc cooldown vào DB (sống sót qua restart)
    cfg_repo.set_companion_last_post.assert_awaited_once_with("gpk", NOW)


@pytest.mark.asyncio
async def test_companion_tick_skips_first_run_after_restart():
    # tasks.loop chạy lượt đầu NGAY khi online -> phải BỎ để bot không tự nói mỗi lần restart.
    cog = _cog(_cfg())
    cog._handle_guild = AsyncMock()
    cog.bot.guilds = [SimpleNamespace(id=100)]
    await cog.companion_tick()  # lượt đầu (vừa restart) -> bỏ qua
    cog._handle_guild.assert_not_awaited()
    await cog.companion_tick()  # lượt kế (đã qua 1 chu kỳ) -> chạy bình thường
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
    stub.decide.assert_not_awaited()  # KHÔNG gọi AI khi không có gì


@pytest.mark.asyncio
async def test_handle_guild_cooldown_blocks(monkeypatch):
    stub = MagicMock()
    stub.decide = AsyncMock(return_value="hi")
    _patch(monkeypatch, stub)
    # vừa post cách đây 60s, cooldown 45' -> còn chặn
    cog = _cog(_cfg(companion_cooldown_min=45, companion_last_post_at=NOW - timedelta(seconds=60)))
    ch = _channel()
    await cog._handle_guild(_guild(ch, members=[_member("An", game="LoL")]), now=NOW)
    stub.decide.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_guild_cooldown_survives_restart(monkeypatch):
    # CHỐNG BUG: cooldown đọc từ DB (cfg) chứ KHÔNG phải RAM -> restart (cog mới tinh) vẫn nhớ.
    stub = MagicMock()
    stub.decide = AsyncMock(return_value="hi")
    _patch(monkeypatch, stub)
    cfg = _cfg(companion_cooldown_min=45, companion_last_post_at=NOW - timedelta(minutes=5))
    cog = _cog(cfg)  # 'cog mới' mô phỏng sau restart, không có state RAM
    ch = _channel()
    await cog._handle_guild(_guild(ch, members=[_member("An", game="LoL")]), now=NOW)
    stub.decide.assert_not_awaited()  # 5' < 45' -> vẫn im dù vừa restart


@pytest.mark.asyncio
async def test_handle_guild_skip_silenced(monkeypatch):
    stub = MagicMock()
    stub.decide = AsyncMock(return_value=None)  # AI chọn SKIP
    cfg_repo = _patch(monkeypatch, stub)
    cog = _cog(_cfg())
    ch = _channel()
    await cog._handle_guild(_guild(ch, members=[_member("An", game="LoL")]), now=NOW)
    ch.send.assert_not_awaited()
    cfg_repo.set_companion_last_post.assert_not_awaited()  # không post -> không set cooldown


# ---------- real-time: on_presence_update (vừa bật game) ----------


def _pmember(guild, game=None, name="An", uid=1):
    """Member cho sự kiện presence: có .guild + .mention + activities."""
    acts = [SimpleNamespace(type=discord.ActivityType.playing, name=game)] if game else []
    return SimpleNamespace(
        id=uid, bot=False, display_name=name, mention=f"<@{uid}>", activities=acts, guild=guild
    )


@pytest.mark.asyncio
async def test_presence_event_posts_when_game_started(monkeypatch):
    stub = MagicMock()
    stub.decide = AsyncMock(return_value="Ê <@1> chơi Valorant một mình kìa, ai vô gánh ko")
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
    assert "VỪA MỚI" in snap and "Valorant" in snap  # snapshot nêu rõ sự kiện vừa bật game


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
    # vừa nói cách đây 60s, cooldown 5' -> còn chặn
    cog = _cog(_cfg(companion_cooldown_min=5, companion_last_post_at=NOW - timedelta(seconds=60)))
    member = _pmember(None, game="Valorant")
    await cog._handle_presence_event(_guild(_channel(), [member]), member, ["Valorant"], now=NOW)
    stub.decide.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_presence_update_fires_only_on_new_game(monkeypatch):
    cog = _cog(_cfg())
    cog._handle_presence_event = AsyncMock()
    g = SimpleNamespace(id=100)
    # chưa chơi -> vừa bật Valorant: PHẢI fire
    await cog.on_presence_update(_pmember(g), _pmember(g, game="Valorant"))
    cog._handle_presence_event.assert_awaited_once()
    # đang chơi sẵn Valorant, presence đổi vì lý do khác: KHÔNG fire
    cog._handle_presence_event.reset_mock()
    await cog.on_presence_update(_pmember(g, game="Valorant"), _pmember(g, game="Valorant"))
    cog._handle_presence_event.assert_not_awaited()


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
    # model lỡ tag chính bot -> phải bị gỡ trước khi gửi
    stub = MagicMock()
    stub.decide = AsyncMock(return_value="Ê <@1> vào chơi đi, <@777> tao cũng tham gia")
    _patch(monkeypatch, stub)
    cog = _cog(_cfg())
    cog.bot.user = SimpleNamespace(id=777)  # bot là 777
    ch = _channel()
    member = _pmember(None, game="Valorant", uid=1)
    await cog._handle_presence_event(_guild(ch, [member]), member, ["chơi Valorant"], now=NOW)
    sent = ch.send.call_args.args[0]
    assert "<@777>" not in sent  # mention bot đã bị gỡ
    assert "<@1>" in sent  # mention người khác vẫn còn
