from pydantic import BaseModel, ConfigDict


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    discord_id: int
    username: str
    avatar_url: str | None = None
