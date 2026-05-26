import discord
import pytest
from discord.ext import commands

from app.bot.cogs.moderation import ModerationCog, _parse_duration
from tests.fakes.discord import FakeDiscordClient


def test_parse_duration():
    assert _parse_duration("30m") == 1800
    assert _parse_duration("2h") == 7200
    assert _parse_duration("1d") == 86400
    assert _parse_duration("45s") == 45
    assert _parse_duration("xyz") is None
    assert _parse_duration("10") is None


@pytest.mark.asyncio
async def test_cog_exposes_expected_commands():
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    cog = ModerationCog(bot, FakeDiscordClient())
    names = {c.name for c in cog.walk_app_commands()}
    assert {"ban", "kick", "mute", "unmute", "unban", "warn", "warnings", "case"} <= names
