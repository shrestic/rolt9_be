# Auto-escalation logic for /warn. When a user gets warned for the Nth time,
# if any rule has threshold = N, the bot automatically applies the rule's
# action (mute or ban).
#
# Because /warn adds exactly one case at a time, we only need to check "is
# there a rule whose threshold equals the current count" — we don't need
# "rule whose threshold <= current count", since the previous increment
# would have already triggered any earlier rule. Sorting by threshold isn't
# strictly required for exact-match, but it keeps output deterministic.

from typing import Any


def next_escalation(active_warns: int, rules: list[dict[str, Any]]) -> dict[str, Any] | None:
    for rule in sorted(rules, key=lambda r: r.get("threshold", 0)):
        if rule.get("threshold") == active_warns:
            return rule
    return None
