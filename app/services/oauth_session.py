# OAuthSessionService — manages the lifecycle of a logged-in user's access token.
#
# The problem: a Discord access token only lives 7 days. When a user hits an
# API, we need a still-valid token to forward to Discord (e.g. list the user's
# guilds for the permission check). Logic:
#   - Token has >60s left → decrypt from DB and use it as-is
#   - Token has <60s left → use the refresh_token to mint a new one, write the
#                            new pair back to the DB, return the new access token
#
# This service does NOT make HTTP calls directly — HTTP goes through
# DiscordOAuthClient. The service knows about DB encryption (app.core.crypto)
# and the refresh timing policy.

from datetime import UTC, datetime, timedelta

from app.core.crypto import decrypt_str, encrypt_str
from app.discord_io.client import DiscordOAuthClient
from app.discord_io.errors import DiscordError
from app.models.user import User
from app.repositories.user import UserRepository


# Raised when the user's stored refresh token can no longer be exchanged
# (Discord returned an OAuth error, e.g. the user revoked the app). Endpoints
# / dependencies catch this and turn it into HTTP 401 so the FE knows to
# bounce the user back through /auth/discord/login.
class SessionExpiredError(Exception):
    pass


class OAuthSessionService:
    def __init__(self, oauth: DiscordOAuthClient):
        self.oauth = oauth

    async def get_valid_access_token(self, user: User, users: UserRepository) -> str:
        now = datetime.now(UTC)

        # token_expires_at can be naive (sqlite) or aware (postgres) — force
        # to UTC-aware so the comparison is consistent.
        expires_at = user.token_expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)

        # More than 60s left → use the current token. The 60s buffer avoids
        # a race where the token is close to expiry by the time the caller uses it.
        if expires_at - now > timedelta(seconds=60):
            return decrypt_str(user.access_token_enc)

        # Token is near expiry → refresh. If Discord rejects the refresh token
        # (user revoked, token corrupted, etc.) the only recovery is for the
        # user to log in again. Surface that intent clearly.
        refresh_plain = decrypt_str(user.refresh_token_enc)
        try:
            tokens = await self.oauth.refresh_oauth_token(refresh_plain)
        except DiscordError as exc:
            raise SessionExpiredError(
                "Discord refresh token rejected; user must log in again."
            ) from exc

        # Write the new tokens back. upsert (not update) matches the repo's
        # consistent upsert-based pattern for the user row.
        await users.upsert(
            discord_id=user.discord_id,
            username=user.username,
            avatar_url=user.avatar_url,
            access_token_enc=encrypt_str(tokens.access_token),
            refresh_token_enc=encrypt_str(tokens.refresh_token),
            token_expires_at=tokens.expires_at,
        )
        return tokens.access_token
