"""Pure period math for quests — maps a timestamp to the key of the quest
period it falls in. No DB, no I/O.

A quest's progress is scoped to a *period instance* identified by a string key:
daily quests reset every UTC calendar day, weekly quests every ISO week (which
starts Monday — so the reset is Monday 00:00 UTC). The key is stored on
`user_quest_progress.period_key`; a new period simply means a new key, so a new
progress row starts at zero with no cleanup needed.
"""

from datetime import datetime

DAILY = "daily"
WEEKLY = "weekly"
PERIODS = {DAILY, WEEKLY}

OBJECTIVE_EARN_COINS = "earn_coins"
OBJECTIVE_DAILY_CLAIM = "daily_claim"
OBJECTIVES = {OBJECTIVE_EARN_COINS, OBJECTIVE_DAILY_CLAIM}


def period_key(period: str, now: datetime) -> str:
    """Return the key of the current period for `period`, computed in UTC.

    - daily  → the UTC calendar date, e.g. "2026-05-30".
    - weekly → the ISO year-week, e.g. "2026-W22". ISO weeks start Monday, so
      this naturally rolls over at Monday 00:00 UTC.

    `now` must be UTC-aware (the service passes a UTC timestamp).
    """
    if period == WEEKLY:
        iso = now.isocalendar()  # (ISO year, ISO week, ISO weekday)
        return f"{iso[0]}-W{iso[1]:02d}"
    return now.date().isoformat()
