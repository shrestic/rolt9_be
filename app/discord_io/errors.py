# These 4 exceptions are the entire surface that service/endpoint/cog code
# sees when calling DiscordClient or DiscordOAuthClient. Adapters (bot.py +
# rest.py) MUST convert any SDK exception (discord.NotFound, httpx.HTTPStatusError,
# etc.) into one of these — feature code never has to `import discord` or
# `httpx` just to catch errors.


# Generic I/O failure — base class used to catch every Discord-side error.
class DiscordError(Exception):
    pass


# The target resource does not exist (guild / user / channel / ban).
# Adapter maps from: discord.NotFound (bot side) / HTTP 404 (REST side).
class DiscordNotFound(DiscordError):
    pass


# Bot or user lacks permission for the action.
# Adapter maps from: discord.Forbidden / HTTP 403.
class DiscordForbidden(DiscordError):
    pass


# Discord rate limit (429). retry_after_seconds = how long the client should wait.
# This refactor doesn't auto-retry; callers catch the exception if they need to.
class DiscordRateLimited(DiscordError):
    def __init__(self, retry_after_seconds: float):
        super().__init__(f"Rate limited; retry after {retry_after_seconds:.1f}s")
        self.retry_after_seconds = retry_after_seconds
