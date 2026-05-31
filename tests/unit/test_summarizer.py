import contextlib
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.bot.cogs.summarizer as summ_mod
from app.bot.cogs.summarizer import SummarizerCog, _collect_transcript
from app.core.crypto import encrypt_str
from app.models.guild import Guild
from app.models.guild_ai_config import GuildAIConfig
from app.repositories.ai_config import AIConfigRepository
from app.repositories.ai_usage import AIUsageRepository
from app.repositories.guild import GuildRepository
from app.services.ai.ai_gateway import AIGateway
from app.services.ai.provider import FakeAIProvider
from app.services.ai.summarizer_service import SummarizerService

GID = 3030


# ---------- service ----------


async def _svc(db_session, *, enabled=True):
    gid = uuid.uuid4()
    db_session.add(Guild(id=gid, discord_id=GID, name="g", icon_url=None, is_active=True))
    db_session.add(
        GuildAIConfig(
            guild_id=gid,
            enabled=enabled,
            provider="anthropic",
            model="claude-haiku-4-5",
            api_key_enc=encrypt_str("sk-test"),
            monthly_budget_usd=5,
        )
    )
    await db_session.commit()
    gw = AIGateway(
        guild_repo=GuildRepository(db_session),
        config_repo=AIConfigRepository(db_session),
        usage_repo=AIUsageRepository(db_session),
        provider=FakeAIProvider(text="- điểm 1\n- điểm 2"),
    )
    return SummarizerService(gateway=gw)


@pytest.mark.asyncio
async def test_summarize_returns_text(db_session):
    svc = await _svc(db_session)
    out = await svc.summarize(guild_discord_id=GID, transcript="An: hi\nBình: yo")
    assert "điểm 1" in out


@pytest.mark.asyncio
async def test_summarize_disabled_raises(db_session):
    svc = await _svc(db_session, enabled=False)
    with pytest.raises(ValueError):
        await svc.summarize(guild_discord_id=GID, transcript="x")


# ---------- transcript builder ----------


class _FakeHistory:
    def __init__(self, msgs):
        self._msgs = msgs

    def __call__(self, limit):  # channel.history(limit=...)
        async def gen():
            for m in self._msgs[:limit]:
                yield m

        return gen()


def _msg(name, content, bot=False):
    return SimpleNamespace(author=SimpleNamespace(display_name=name, bot=bot), content=content)


@pytest.mark.asyncio
async def test_collect_transcript_skips_bots_and_empty_and_orders_old_to_new():
    # history yields newest-first
    channel = SimpleNamespace(
        history=_FakeHistory(
            [
                _msg("Bình", "tin mới"),
                _msg("Bot", "spam", bot=True),
                _msg("An", "   "),  # empty
                _msg("An", "tin cũ"),
            ]
        )
    )
    transcript = await _collect_transcript(channel, 10)
    assert transcript == "An: tin cũ\nBình: tin mới"


# ---------- cog ----------


def test_cog_registers_command():
    cog = SummarizerCog(MagicMock(), MagicMock())
    names = {c.name for c in cog.get_app_commands()}
    assert "summarize" in names


def _patch(monkeypatch, stub):
    @contextlib.asynccontextmanager
    async def fake_scope():
        yield MagicMock()

    monkeypatch.setattr(summ_mod, "session_scope", fake_scope)
    monkeypatch.setattr(summ_mod, "_build_service", lambda session: stub)


def _interaction():
    inter = MagicMock()
    inter.guild_id = 100
    inter.response = SimpleNamespace(defer=AsyncMock(), is_done=MagicMock(return_value=True))
    inter.followup = SimpleNamespace(send=AsyncMock())
    inter.channel = SimpleNamespace(history=_FakeHistory([_msg("An", "hello")]))
    return inter


@pytest.mark.asyncio
async def test_summarize_command_replies(monkeypatch):
    stub = MagicMock()
    stub.summarize = AsyncMock(return_value="- tóm tắt")
    _patch(monkeypatch, stub)
    cog = SummarizerCog(MagicMock(), MagicMock())
    inter = _interaction()
    await cog.summarize.callback(cog, inter, 30)
    msg = inter.followup.send.call_args.args[0]
    assert "tóm tắt" in msg


@pytest.mark.asyncio
async def test_summarize_empty_channel(monkeypatch):
    stub = MagicMock()
    stub.summarize = AsyncMock()
    _patch(monkeypatch, stub)
    cog = SummarizerCog(MagicMock(), MagicMock())
    inter = _interaction()
    inter.channel = SimpleNamespace(history=_FakeHistory([]))
    await cog.summarize.callback(cog, inter, 30)
    msg = inter.followup.send.call_args.args[0]
    assert "Không có tin" in msg
    stub.summarize.assert_not_awaited()
