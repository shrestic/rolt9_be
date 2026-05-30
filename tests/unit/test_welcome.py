import contextlib
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.bot.cogs.welcome as welcome_mod
from app.bot.cogs.welcome import WelcomeCog
from app.models.guild import Guild
from app.models.guild_ai_config import GuildAIConfig
from app.models.guild_welcome_config import GuildWelcomeConfig
from app.repositories.ai_config import AIConfigRepository
from app.repositories.ai_usage import AIUsageRepository
from app.repositories.guild import GuildRepository
from app.repositories.welcome_config import WelcomeConfigRepository
from app.services.ai.ai_gateway import AIGateway
from app.services.ai.provider import FakeAIProvider
from app.services.welcome.template import render_template
from app.services.welcome.welcome_service import WelcomeService

GID = 6060


# ---------- pure template ----------


def test_render_template_substitutes():
    out = render_template("Hi {user} @ {server} (#{count})", user="@An", server="X", count=5)
    assert out == "Hi @An @ X (#5)"


def test_render_template_ignores_unknown_braces():
    assert render_template("{foo} {user}", user="@An", server="X", count=1) == "{foo} @An"


# ---------- service ----------


async def _svc(db_session, *, ai_available=True, **welcome_kw):
    gid = uuid.uuid4()
    db_session.add(Guild(id=gid, discord_id=GID, name="X", icon_url=None, is_active=True))
    db_session.add(GuildAIConfig(guild_id=gid, enabled=True, monthly_token_budget=100_000))
    db_session.add(GuildWelcomeConfig(guild_id=gid, **welcome_kw))
    await db_session.commit()

    class _Prov(FakeAIProvider):
        available = ai_available

    svc = WelcomeService(
        guild_repo=GuildRepository(db_session),
        config_repo=WelcomeConfigRepository(db_session),
        gateway=AIGateway(
            guild_repo=GuildRepository(db_session),
            config_repo=AIConfigRepository(db_session),
            usage_repo=AIUsageRepository(db_session),
            provider=_Prov(text="Chào bạn mới! 🎉"),
        ),
    )
    return svc


@pytest.mark.asyncio
async def test_welcome_template(db_session):
    svc = await _svc(
        db_session, enabled=True, channel_id=999, welcome_template="Hi {user} thứ {count}"
    )
    res = await svc.build_welcome(
        guild_discord_id=GID, user_mention="@An", user_name="An", server_name="X", member_count=7
    )
    assert res == (999, "Hi @An thứ 7")


@pytest.mark.asyncio
async def test_welcome_ai(db_session):
    svc = await _svc(
        db_session, enabled=True, channel_id=999, ai_welcome=True, welcome_template="tpl"
    )
    res = await svc.build_welcome(
        guild_discord_id=GID, user_mention="@An", user_name="An", server_name="X", member_count=7
    )
    assert res[0] == 999
    assert "Chào bạn mới" in res[1]
    assert res[1].startswith("@An ")


@pytest.mark.asyncio
async def test_welcome_ai_falls_back_when_unavailable(db_session):
    svc = await _svc(
        db_session,
        ai_available=False,
        enabled=True,
        channel_id=999,
        ai_welcome=True,
        welcome_template="Hi {user}",
    )
    res = await svc.build_welcome(
        guild_discord_id=GID, user_mention="@An", user_name="An", server_name="X", member_count=1
    )
    assert res == (999, "Hi @An")  # fell back to template


@pytest.mark.asyncio
async def test_welcome_disabled_or_no_channel(db_session):
    svc = await _svc(db_session, enabled=False, channel_id=999)
    assert (
        await svc.build_welcome(
            guild_discord_id=GID, user_mention="@A", user_name="A", server_name="X", member_count=1
        )
        is None
    )


@pytest.mark.asyncio
async def test_leave(db_session):
    svc = await _svc(
        db_session, enabled=True, channel_id=999, leave_enabled=True, leave_template="Bye {user}"
    )
    res = await svc.build_leave(
        guild_discord_id=GID, user_name="An", server_name="X", member_count=3
    )
    assert res == (999, "Bye An")


# ---------- cog ----------


def _patch(monkeypatch, stub):
    @contextlib.asynccontextmanager
    async def fake_scope():
        yield MagicMock()

    monkeypatch.setattr(welcome_mod, "session_scope", fake_scope)
    monkeypatch.setattr(welcome_mod, "_build_service", lambda session: stub)


def _member():
    return SimpleNamespace(
        guild=SimpleNamespace(id=100, name="X", member_count=10),
        mention="<@1>",
        display_name="An",
    )


@pytest.mark.asyncio
async def test_on_member_join_posts(monkeypatch):
    stub = MagicMock()
    stub.build_welcome = AsyncMock(return_value=(999, "Welcome!"))
    _patch(monkeypatch, stub)
    discord_io = MagicMock()
    discord_io.post_to_channel = AsyncMock()
    cog = WelcomeCog(MagicMock(), discord_io)
    await cog.on_member_join(_member())
    discord_io.post_to_channel.assert_awaited_once()


@pytest.mark.asyncio
async def test_on_member_join_no_config_no_post(monkeypatch):
    stub = MagicMock()
    stub.build_welcome = AsyncMock(return_value=None)
    _patch(monkeypatch, stub)
    discord_io = MagicMock()
    discord_io.post_to_channel = AsyncMock()
    cog = WelcomeCog(MagicMock(), discord_io)
    await cog.on_member_join(_member())
    discord_io.post_to_channel.assert_not_awaited()
