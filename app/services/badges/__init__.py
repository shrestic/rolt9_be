"""Badges feature package — achievement badges from a hardcoded catalog."""

from app.services.badges.badge_service import BadgeService
from app.services.badges.catalog import BadgeDef

__all__ = ["BadgeDef", "BadgeService"]
