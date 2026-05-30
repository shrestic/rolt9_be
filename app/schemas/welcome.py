"""Pydantic schemas for the Welcome plugin (dashboard settings).

`channel_id` is a string on the wire (snowflake precision), like the leveling
notification channel; the endpoint coerces to int at the DB boundary.
"""

from pydantic import BaseModel, Field


class WelcomeSettings(BaseModel):
    enabled: bool = False
    channel_id: str | None = None
    welcome_template: str = Field(default="", max_length=1000)
    ai_welcome: bool = False
    leave_enabled: bool = False
    leave_template: str = Field(default="", max_length=1000)


__all__ = ["WelcomeSettings"]
