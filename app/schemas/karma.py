"""Pydantic schemas for the Karma feature (dashboard settings + leaderboard)."""

from pydantic import BaseModel


class KarmaSettings(BaseModel):
    """Per-guild karma configuration (just the on/off switch in v1)."""

    enabled: bool = False


class KarmaLeaderboardEntryOut(BaseModel):
    """One row of the karma leaderboard. user_id is a string (snowflake)."""

    rank: int
    user_id: str
    points: int


class KarmaLeaderboardPageOut(BaseModel):
    """Paginated karma leaderboard response."""

    items: list[KarmaLeaderboardEntryOut]
    total: int
    page: int
    page_size: int


__all__ = ["KarmaLeaderboardEntryOut", "KarmaLeaderboardPageOut", "KarmaSettings"]
