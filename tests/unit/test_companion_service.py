import uuid
from types import SimpleNamespace

import discord
import pytest

from app.core.crypto import encrypt_str
from app.models.guild import Guild
from app.models.guild_ai_config import GuildAIConfig
from app.repositories.ai_config import AIConfigRepository
from app.repositories.ai_usage import AIUsageRepository
from app.repositories.guild import GuildRepository
from app.services.ai.ai_gateway import AIGateway
from app.services.ai.companion_service import (
    CompanionService,
    build_companion_system,
    build_snapshot,
)
from app.services.ai.provider import FakeAIProvider


def _member(name, games=(), bot=False):
    acts = [SimpleNamespace(type=discord.ActivityType.playing, name=g) for g in games]
    uid = hash(name) % 10000
    return SimpleNamespace(id=uid, display_name=name, bot=bot, activities=acts, mention=f"<@{uid}>")


def test_build_snapshot_game_alone():
    members = [_member("An", games=["LoL"]), _member("Bot", games=["LoL"], bot=True)]
    out = build_snapshot(members, [], [], bot_id=999)
    assert out is not None
    assert "MỘT MÌNH" in out and "An" in out and "Bot" not in out


def test_build_snapshot_includes_mention_for_ping():
    # Snapshot phải kèm '<@id>' để model @ping được đúng người
    an = _member("An", games=["Valorant"])
    out = build_snapshot([an], [], [], bot_id=999)
    assert f"<@{an.id}>" in out


def test_build_snapshot_group_game():
    members = [
        _member("An", ["Valorant"]),
        _member("Binh", ["Valorant"]),
        _member("Cuong", ["Valorant"]),
    ]
    out = build_snapshot(members, [], [], 999)
    assert "3 người" in out and "Valorant" in out


def test_build_snapshot_voice_and_chat():
    vc = SimpleNamespace(name="General", members=[SimpleNamespace(display_name="An", bot=False)])
    msgs = [
        SimpleNamespace(author=SimpleNamespace(display_name="Binh", bot=False), content="hello")
    ]
    out = build_snapshot([], [vc], msgs, 999)
    assert "một mình" in out.lower() and "Binh" in out


def test_build_snapshot_empty_none():
    assert build_snapshot([], [], [], 999) is None


def test_build_companion_system_persona():
    s = build_companion_system("Bạn là mèo máy")
    assert "mèo máy" in s and "SKIP" in s


def test_build_companion_system_includes_memory_doc():
    s = build_companion_system("Bạn là mèo máy", "- gọi An là thằng loz")
    assert "thằng loz" in s and "TRÍ NHỚ SERVER" in s


async def _svc(db_session, provider, *, discord_id=4242, enabled=True):
    gid = uuid.uuid4()
    db_session.add(Guild(id=gid, discord_id=discord_id, name="g", icon_url=None, is_active=True))
    cfg = GuildAIConfig(guild_id=gid, enabled=enabled)
    if enabled:
        cfg.provider = "deepseek"
        cfg.model = "deepseek-chat"
        cfg.api_key_enc = encrypt_str("sk")
        cfg.monthly_budget_usd = 5
    db_session.add(cfg)
    await db_session.commit()
    gw = AIGateway(
        guild_repo=GuildRepository(db_session),
        config_repo=AIConfigRepository(db_session),
        usage_repo=AIUsageRepository(db_session),
        provider=provider,
    )
    return CompanionService(gateway=gw)


@pytest.mark.asyncio
async def test_decide_skip(db_session):
    svc = await _svc(db_session, FakeAIProvider(text="SKIP", cost_usd=0.0))
    assert await svc.decide(guild_discord_id=4242, snapshot="tình hình", persona="") is None


@pytest.mark.asyncio
async def test_decide_says_something(db_session):
    svc = await _svc(db_session, FakeAIProvider(text="Ê An chơi một mình kìa 👀", cost_usd=0.0))
    out = await svc.decide(guild_discord_id=4242, snapshot="An chơi LoL", persona="")
    assert "An" in out


@pytest.mark.asyncio
async def test_decide_swallows_valueerror(db_session):
    svc = await _svc(db_session, FakeAIProvider(cost_usd=0.0), discord_id=4343, enabled=False)
    assert await svc.decide(guild_discord_id=4343, snapshot="x", persona="") is None
