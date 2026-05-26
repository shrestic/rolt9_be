# Actor is a thin wrapper for a user in moderation context. It exists so the
# service layer never has to take a discord.Member / discord.User directly.
#
# Cog (bot side)       → already has a discord.Member from the interaction → use Actor.from_member()
# Endpoint (REST side) → already has user_id + username from DB / params  → use Actor(...) directly
#
# Service code only ever sees Actor.user_id + Actor.username — it has no
# knowledge of any SDK type.

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Actor:
    user_id: int
    username: str

    # Build from a discord.Member or discord.User. Typed as Any to keep this
    # file SDK-free; the object only needs an `.id` and a usable `__str__`
    # (both Member and User satisfy that).
    @classmethod
    def from_member(cls, m: Any) -> "Actor":
        return cls(user_id=int(m.id), username=str(m))
