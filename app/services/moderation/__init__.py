# Public surface of the moderation module — re-exports so callers can
# `from app.services.moderation import ModerationService, Actor` without
# reaching into sub-modules.

from app.services.moderation.actor import Actor
from app.services.moderation.embeds import build_case_embed
from app.services.moderation.escalation import next_escalation
from app.services.moderation.service import ModerationService

__all__ = ["Actor", "ModerationService", "build_case_embed", "next_escalation"]
