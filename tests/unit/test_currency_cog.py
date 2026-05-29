from unittest.mock import MagicMock

from app.bot.cogs.currency import CurrencyCog


def test_cog_registers_commands():
    cog = CurrencyCog(MagicMock(), MagicMock())
    names = {c.name for c in cog.get_app_commands()}
    # /balance, /daily, /pay, /baltop, and the /eco group
    assert {"balance", "daily", "pay", "baltop", "eco"} <= names
