"""Pydantic schemas for the Badges feature (dashboard settings + catalog)."""

from pydantic import BaseModel


class BadgeSettings(BaseModel):
    """Per-guild badges configuration (just the on/off switch in v1)."""

    enabled: bool = False


class BadgeCatalogEntry(BaseModel):
    """One badge in the read-only catalog the dashboard renders."""

    key: str
    name: str
    emoji: str
    description: str
    stat: str
    threshold: int


__all__ = ["BadgeCatalogEntry", "BadgeSettings"]
