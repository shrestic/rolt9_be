from pydantic import BaseModel


class GuildSummary(BaseModel):
    discord_id: str
    name: str
    icon_url: str | None = None
    bot_present: bool
    can_manage: bool = True


class ChannelDTO(BaseModel):
    id: str
    name: str
    type: int


class RoleDTO(BaseModel):
    id: str
    name: str


class GuildOverview(BaseModel):
    discord_id: str
    name: str
    icon_url: str | None = None
    member_count: int
    channels: list[ChannelDTO]
    roles: list[RoleDTO]
    bot_present: bool
