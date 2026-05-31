import contextlib
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.bot.cogs.chat as chat_mod
from app.bot.cogs.chat import ChatCog
from app.core.crypto import encrypt_str
from app.models.guild import Guild
from app.models.guild_ai_config import GuildAIConfig
from app.repositories.ai_config import AIConfigRepository
from app.repositories.ai_usage import AIUsageRepository
from app.repositories.guild import GuildRepository
from app.services.ai.ai_gateway import AIGateway
from app.services.ai.chat_service import DEFAULT_PERSONA, ChatService
from app.services.ai.provider import FakeAIProvider

GID = 5050


class _CapProvider(FakeAIProvider):
    """Captures the system prompt it was called with, for persona assertions."""

    def __init__(self):
        super().__init__(text="ok")
        self.last_system = None

    async def complete(self, *, provider, model, api_key, system, prompt, max_tokens, history=None):
        self.last_system = system
        return await super().complete(
            provider=provider,
            model=model,
            api_key=api_key,
            system=system,
            prompt=prompt,
            max_tokens=max_tokens,
            history=history,
        )


async def _svc(db_session, *, persona="", enabled=True):
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
            persona=persona,
        )
    )
    await db_session.commit()
    provider = _CapProvider()
    svc = ChatService(
        gateway=AIGateway(
            guild_repo=GuildRepository(db_session),
            config_repo=AIConfigRepository(db_session),
            usage_repo=AIUsageRepository(db_session),
            provider=provider,
        ),
        guild_repo=GuildRepository(db_session),
        config_repo=AIConfigRepository(db_session),
    )
    return svc, provider


@pytest.mark.asyncio
async def test_chat_uses_custom_persona(db_session):
    svc, provider = await _svc(db_session, persona="Bạn là mèo máy nói trống không.")
    out = await svc.chat(guild_discord_id=GID, message="hi")
    assert out == "ok"
    assert provider.last_system == "Bạn là mèo máy nói trống không."


@pytest.mark.asyncio
async def test_chat_falls_back_to_default_persona(db_session):
    svc, provider = await _svc(db_session, persona="")
    await svc.chat(guild_discord_id=GID, message="hi")
    assert provider.last_system == DEFAULT_PERSONA


@pytest.mark.asyncio
async def test_chat_disabled_raises(db_session):
    svc, _ = await _svc(db_session, enabled=False)
    with pytest.raises(ValueError):
        await svc.chat(guild_discord_id=GID, message="hi")


def test_cog_registers_command():
    cog = ChatCog(MagicMock(), MagicMock())
    names = {c.name for c in cog.get_app_commands()}
    assert "chat" in names


@pytest.mark.asyncio
async def test_chat_command_replies(monkeypatch):
    stub = MagicMock()
    stub.chat = AsyncMock(return_value="Xin chào!")

    @contextlib.asynccontextmanager
    async def fake_scope():
        yield MagicMock()

    monkeypatch.setattr(chat_mod, "session_scope", fake_scope)
    monkeypatch.setattr(chat_mod, "_build_service", lambda session: stub)
    cog = ChatCog(MagicMock(), MagicMock())
    inter = MagicMock()
    inter.guild_id = 100
    inter.response = SimpleNamespace(defer=AsyncMock(), is_done=MagicMock(return_value=True))
    inter.followup = SimpleNamespace(send=AsyncMock())
    await cog.chat.callback(cog, inter, "hi")
    assert "Xin chào!" in inter.followup.send.call_args.args[0]
