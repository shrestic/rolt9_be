import httpx

DISCORD_API = "https://discord.com/api"


class DiscordAPIClient:
    async def list_user_guilds(self, access_token: str) -> list[dict]:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{DISCORD_API}/users/@me/guilds",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            r.raise_for_status()
            return r.json()

    async def get_guild_with_counts(self, guild_id: str, bot_token: str) -> dict:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{DISCORD_API}/guilds/{guild_id}",
                headers={"Authorization": f"Bot {bot_token}"},
                params={"with_counts": "true"},
            )
            r.raise_for_status()
            return r.json()

    async def list_guild_channels(self, guild_id: str, bot_token: str) -> list[dict]:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{DISCORD_API}/guilds/{guild_id}/channels",
                headers={"Authorization": f"Bot {bot_token}"},
            )
            r.raise_for_status()
            return r.json()

    async def list_guild_roles(self, guild_id: str, bot_token: str) -> list[dict]:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{DISCORD_API}/guilds/{guild_id}/roles",
                headers={"Authorization": f"Bot {bot_token}"},
            )
            r.raise_for_status()
            return r.json()
