import uuid

import pytest

from app.core.crypto import encrypt_str
from app.models.guild import Guild
from app.models.guild_ai_config import GuildAIConfig
from app.repositories.ai_config import AIConfigRepository
from app.repositories.ai_usage import AIUsageRepository
from app.repositories.guild import GuildRepository
from app.services.ai.ai_gateway import AIGateway
from app.services.ai.provider import FakeAIProvider
from app.services.ai.tools.registry import ToolContext
from app.services.ai.tools.runner import MAX_TOOL_STEPS, run_with_tools

GID = 8888


async def _gw(db_session, provider):
    gid = uuid.uuid4()
    db_session.add(Guild(id=gid, discord_id=GID, name="g", icon_url=None, is_active=True))
    db_session.add(
        GuildAIConfig(
            guild_id=gid,
            enabled=True,
            provider="deepseek",
            model="deepseek-chat",
            api_key_enc=encrypt_str("sk-test"),
            monthly_budget_usd=5,
        )
    )
    await db_session.commit()
    return AIGateway(
        guild_repo=GuildRepository(db_session),
        config_repo=AIConfigRepository(db_session),
        usage_repo=AIUsageRepository(db_session),
        provider=provider,
    )


@pytest.mark.asyncio
async def test_runner_executes_tool_then_answers(db_session):
    prov = FakeAIProvider(
        turns=[
            {"tool_calls": [{"id": "c1", "name": "current_time", "arguments": "{}"}]},
            {"text": "Bây giờ là buổi sáng."},
        ],
        cost_usd=0.0,
    )
    gw = await _gw(db_session, prov)
    out = await run_with_tools(
        gateway=gw,
        guild_discord_id=GID,
        system="sys",
        history=[],
        user_text="mấy giờ",
        ctx=ToolContext(guild_snapshot={}),
        has_search=False,
    )
    assert out == "Bây giờ là buổi sáng."


@pytest.mark.asyncio
async def test_runner_degrades_gracefully_on_empty_text(db_session):
    # Reasoning model cạn token -> complete_raw trả text="" (allow_empty) -> runner trả câu
    # fallback thân thiện, KHÔNG phun lỗi kỹ thuật "Model dùng hết token..." ra người dùng.
    prov = FakeAIProvider(turns=[{"text": ""}], cost_usd=0.0)
    gw = await _gw(db_session, prov)
    out = await run_with_tools(
        gateway=gw,
        guild_discord_id=GID,
        system="sys",
        history=[],
        user_text="làm gì đó đi",
        ctx=ToolContext(guild_snapshot={}),
        has_search=False,
    )
    assert out and "thử lại" in out.lower()


@pytest.mark.asyncio
async def test_runner_forces_answer_at_cap(db_session):
    turns = [
        {"tool_calls": [{"id": f"c{i}", "name": "current_time", "arguments": "{}"}]}
        for i in range(MAX_TOOL_STEPS)
    ] + [{"text": "câu trả lời cuối"}]
    gw = await _gw(db_session, FakeAIProvider(turns=turns, cost_usd=0.0))
    out = await run_with_tools(
        gateway=gw,
        guild_discord_id=GID,
        system="s",
        history=[],
        user_text="x",
        ctx=ToolContext(guild_snapshot={}),
        has_search=False,
    )
    assert out == "câu trả lời cuối"


@pytest.mark.asyncio
async def test_runner_fallback_on_empty(db_session):
    gw = await _gw(db_session, FakeAIProvider(text="", cost_usd=0.0))
    out = await run_with_tools(
        gateway=gw,
        guild_discord_id=GID,
        system="s",
        history=[],
        user_text="x",
        ctx=ToolContext(guild_snapshot={}),
        has_search=False,
    )
    assert "thử lại" in out.lower()
