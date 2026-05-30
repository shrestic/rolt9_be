import contextlib
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.bot.cogs.ask as ask_mod
from app.bot.cogs.ask import AskCog
from app.models.guild import Guild
from app.models.guild_ai_config import GuildAIConfig
from app.repositories.ai_config import AIConfigRepository
from app.repositories.ai_usage import AIUsageRepository
from app.repositories.guild import GuildRepository
from app.repositories.kb import KbRepository
from app.services.ai.ai_gateway import AIGateway
from app.services.ai.ask_service import AskService
from app.services.ai.provider import FakeAIProvider

GID = 4040


async def _setup(db_session, *, enabled=True, with_kb=True):
    gid = uuid.uuid4()
    db_session.add(Guild(id=gid, discord_id=GID, name="g", icon_url=None, is_active=True))
    db_session.add(GuildAIConfig(guild_id=gid, enabled=enabled, monthly_token_budget=100_000))
    await db_session.commit()
    if with_kb:
        await KbRepository(db_session).create(gid, title="Giờ mở cửa", content="9h-21h hằng ngày.")
        await db_session.commit()
    svc = AskService(
        gateway=AIGateway(
            guild_repo=GuildRepository(db_session),
            config_repo=AIConfigRepository(db_session),
            usage_repo=AIUsageRepository(db_session),
            provider=FakeAIProvider(text="Mở 9h-21h."),
        ),
        guild_repo=GuildRepository(db_session),
        kb_repo=KbRepository(db_session),
    )
    return gid, svc


@pytest.mark.asyncio
async def test_kb_repo_crud(db_session):
    gid = uuid.uuid4()
    db_session.add(Guild(id=gid, discord_id=1, name="g", icon_url=None, is_active=True))
    await db_session.commit()
    repo = KbRepository(db_session)
    e = await repo.create(gid, title="t", content="c")
    assert [x.title for x in await repo.list_for_guild(gid)] == ["t"]
    await repo.delete(e)
    assert await repo.list_for_guild(gid) == []


@pytest.mark.asyncio
async def test_ask_answers_from_kb(db_session):
    _, svc = await _setup(db_session)
    out = await svc.ask(guild_discord_id=GID, question="Mấy giờ mở?")
    assert "9h-21h" in out


@pytest.mark.asyncio
async def test_ask_empty_kb_raises(db_session):
    _, svc = await _setup(db_session, with_kb=False)
    with pytest.raises(ValueError):
        await svc.ask(guild_discord_id=GID, question="x")


@pytest.mark.asyncio
async def test_ask_disabled_raises(db_session):
    _, svc = await _setup(db_session, enabled=False)
    with pytest.raises(ValueError):
        await svc.ask(guild_discord_id=GID, question="x")


def test_cog_registers_command():
    cog = AskCog(MagicMock(), MagicMock())
    names = {c.name for c in cog.get_app_commands()}
    assert "ask" in names


def _patch(monkeypatch, stub):
    @contextlib.asynccontextmanager
    async def fake_scope():
        yield MagicMock()

    monkeypatch.setattr(ask_mod, "session_scope", fake_scope)
    monkeypatch.setattr(ask_mod, "_build_service", lambda session: stub)


def _interaction():
    inter = MagicMock()
    inter.guild_id = 100
    inter.response = SimpleNamespace(defer=AsyncMock(), is_done=MagicMock(return_value=True))
    inter.followup = SimpleNamespace(send=AsyncMock())
    return inter


@pytest.mark.asyncio
async def test_ask_command_replies(monkeypatch):
    stub = MagicMock()
    stub.ask = AsyncMock(return_value="Mở 9h-21h.")
    _patch(monkeypatch, stub)
    cog = AskCog(MagicMock(), MagicMock())
    inter = _interaction()
    await cog.ask.callback(cog, inter, "Mấy giờ mở?")
    msg = inter.followup.send.call_args.args[0]
    assert "9h-21h" in msg


@pytest.mark.asyncio
async def test_ask_command_error(monkeypatch):
    stub = MagicMock()
    stub.ask = AsyncMock(side_effect=ValueError("Server chưa có kho tri thức nào"))
    _patch(monkeypatch, stub)
    cog = AskCog(MagicMock(), MagicMock())
    inter = _interaction()
    await cog.ask.callback(cog, inter, "x")
    msg = inter.followup.send.call_args.args[0]
    assert "❌" in msg
