from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx

from app.core.config import settings

DISCORD_API = "https://discord.com/api"


@dataclass
class DiscordTokens:
    access_token: str
    refresh_token: str
    expires_at: datetime
    scope: str


@dataclass
class DiscordUserInfo:
    discord_id: int
    username: str
    avatar_url: str | None


class DiscordOAuthService:
    async def exchange_code(self, code: str) -> DiscordTokens:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{DISCORD_API}/oauth2/token",
                data={
                    "client_id": settings.DISCORD_CLIENT_ID,
                    "client_secret": settings.DISCORD_CLIENT_SECRET,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": settings.DISCORD_REDIRECT_URI,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            r.raise_for_status()
            data = r.json()
        return DiscordTokens(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=datetime.now(UTC) + timedelta(seconds=data["expires_in"]),
            scope=data.get("scope", ""),
        )

    async def refresh(self, refresh_token: str) -> DiscordTokens:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{DISCORD_API}/oauth2/token",
                data={
                    "client_id": settings.DISCORD_CLIENT_ID,
                    "client_secret": settings.DISCORD_CLIENT_SECRET,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            r.raise_for_status()
            data = r.json()
        return DiscordTokens(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=datetime.now(UTC) + timedelta(seconds=data["expires_in"]),
            scope=data.get("scope", ""),
        )

    async def get_me(self, access_token: str) -> DiscordUserInfo:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{DISCORD_API}/users/@me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            r.raise_for_status()
            data = r.json()
        avatar_url = (
            f"https://cdn.discordapp.com/avatars/{data['id']}/{data['avatar']}.png"
            if data.get("avatar")
            else None
        )
        return DiscordUserInfo(
            discord_id=int(data["id"]),
            username=data["username"],
            avatar_url=avatar_url,
        )

    async def get_valid_access_token(self, user, user_repo) -> str:
        """Return a plaintext access token, refreshing first if within 60s of expiry.

        Persists the new token back to the user row if a refresh happens.
        """
        from app.core.crypto import decrypt_str, encrypt_str

        now = datetime.now(UTC)
        expires_at = user.token_expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at - now > timedelta(seconds=60):
            return decrypt_str(user.access_token_enc)

        refresh_plain = decrypt_str(user.refresh_token_enc)
        tokens = await self.refresh(refresh_plain)
        await user_repo.upsert(
            discord_id=user.discord_id,
            username=user.username,
            avatar_url=user.avatar_url,
            access_token_enc=encrypt_str(tokens.access_token),
            refresh_token_enc=encrypt_str(tokens.refresh_token),
            token_expires_at=tokens.expires_at,
        )
        return tokens.access_token
