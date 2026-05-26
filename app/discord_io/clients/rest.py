# RestDiscordOAuthClient — implements DiscordOAuthClient via httpx.
# This is the ONLY OAuth-side adapter we keep after merging the bot into the
# FastAPI process. Bot-side actions (ban, kick, post_to_channel, ...) now go
# through BotDiscordClient, which talks to discord.py directly.
#
# Why is OAuth still here?
#   OAuth uses a user bearer token (issued during the Discord login flow).
#   The bot process never sees a user bearer token, and discord.py has no
#   built-in way to exchange OAuth codes — so OAuth must go through raw HTTP.

from datetime import UTC, datetime, timedelta

import httpx

from app.core.config import settings
from app.discord_io.client import DiscordOAuthClient
from app.discord_io.errors import (
    DiscordError,
    DiscordForbidden,
    DiscordNotFound,
    DiscordRateLimited,
)
from app.discord_io.types import OAuthTokens, UserGuildEntry, UserInfo

DISCORD_API = "https://discord.com/api"
DISCORD_CDN = "https://cdn.discordapp.com"


def _avatar_url(user_id: int | str, avatar_hash: str | None) -> str | None:
    return f"{DISCORD_CDN}/avatars/{user_id}/{avatar_hash}.png" if avatar_hash else None


def _icon_url(guild_id: int | str, icon_hash: str | None) -> str | None:
    return f"{DISCORD_CDN}/icons/{guild_id}/{icon_hash}.png" if icon_hash else None


# Same error-normalization helper as before. Maps HTTP status → our exceptions:
#   404 → DiscordNotFound      (target doesn't exist)
#   403 → DiscordForbidden     (missing permission)
#   429 → DiscordRateLimited   (Discord throttled us)
#   >=400 → DiscordError       (anything else)
def _raise_for(response: httpx.Response) -> None:
    if response.status_code == 404:
        raise DiscordNotFound(f"Discord 404: {response.text}")
    if response.status_code == 403:
        raise DiscordForbidden(f"Discord 403: {response.text}")
    if response.status_code == 429:
        retry_after = 0.0
        try:
            retry_after = float(response.json().get("retry_after", 0))
        except (ValueError, KeyError):
            pass
        raise DiscordRateLimited(retry_after)
    if response.status_code >= 400:
        raise DiscordError(f"Discord {response.status_code}: {response.text}")


class RestDiscordOAuthClient(DiscordOAuthClient):
    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
        redirect_uri: str | None = None,
    ):
        # All three credentials are required to exchange and refresh tokens.
        # Defaults pulled from app settings.
        self._http = http
        self._client_id = client_id or settings.DISCORD_CLIENT_ID
        self._client_secret = client_secret or settings.DISCORD_CLIENT_SECRET
        self._redirect_uri = redirect_uri or settings.DISCORD_REDIRECT_URI

    # ─────────────────────────────────────────────────────────────────────
    # DiscordOAuthClient — OAuth flow + user-bearer reads
    # ─────────────────────────────────────────────────────────────────────

    # OAuth code → tokens. Called from the /auth/discord/callback endpoint
    # right after the user authorizes us on Discord.
    async def exchange_oauth_code(self, code: str) -> OAuthTokens:
        r = await self._http.post(
            f"{DISCORD_API}/oauth2/token",
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self._redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        _raise_for(r)
        data = r.json()
        # Discord returns expires_in (seconds from now); we store an absolute datetime.
        return OAuthTokens(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=datetime.now(UTC) + timedelta(seconds=data["expires_in"]),
            scope=data.get("scope", ""),
        )

    # Trade a refresh token for a fresh access token. OAuthSessionService calls
    # this when the current access token has <60s left.
    async def refresh_oauth_token(self, refresh_token: str) -> OAuthTokens:
        r = await self._http.post(
            f"{DISCORD_API}/oauth2/token",
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        _raise_for(r)
        data = r.json()
        return OAuthTokens(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=datetime.now(UTC) + timedelta(seconds=data["expires_in"]),
            scope=data.get("scope", ""),
        )

    # GET /users/@me using the user bearer token. Returns whoever owns the token.
    # The /auth/discord/callback endpoint calls this right after exchanging the code.
    async def get_user_me(self, access_token: str) -> UserInfo:
        r = await self._http.get(
            f"{DISCORD_API}/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        _raise_for(r)
        data = r.json()
        return UserInfo(
            discord_id=int(data["id"]),
            username=data["username"],
            avatar_url=_avatar_url(data["id"], data.get("avatar")),
        )

    # GET /users/@me/guilds — lists the guilds the user is in, plus their
    # raw permission bitfield in each. PermissionService uses this to filter
    # for guilds the user can manage.
    async def list_guilds_of_user(self, access_token: str) -> list[UserGuildEntry]:
        r = await self._http.get(
            f"{DISCORD_API}/users/@me/guilds",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        _raise_for(r)
        return [
            UserGuildEntry(
                discord_id=int(g["id"]),
                name=g["name"],
                icon_url=_icon_url(g["id"], g.get("icon")),
                owner=bool(g.get("owner", False)),
                permissions=int(g.get("permissions", "0")),
            )
            for g in r.json()
        ]


__all__ = ["RestDiscordOAuthClient"]
