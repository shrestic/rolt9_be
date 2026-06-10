"""Tool registry — schema + dispatch for Claw Agent tools."""

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.services.ai.tools.current_time import run_current_time
from app.services.ai.tools.server_info import run_server_info
from app.services.ai.tools.web_search import run_read_link, run_web_search

log = logging.getLogger(__name__)

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")  # every time the user mentions is Vietnam time


@dataclass
class ToolContext:
    guild_snapshot: dict | None = None
    # Action context (sub-project 3) — only used when include_actions.
    can_act: bool = False
    pending: list = field(default_factory=list)
    role_names: list[str] = field(default_factory=list)
    target_user_ids: list[int] = field(default_factory=list)
    commander_id: int | None = None
    commander_perms: dict = field(default_factory=dict)
    guild_discord_id: int | None = None
    # Server memory doc (OpenClaw-style) — the `remember` tool writes here.
    memory_repo_doc: object | None = None
    guild_pk: object | None = None
    # Reminder — the `remind` tool writes here; channel_id = the channel that will be reminded.
    reminder_repo: object | None = None
    channel_id: int | None = None
    # Subscription (recurring news) — tool `subscribe`/`unsubscribe`/`list_subscriptions`.
    subscription_repo: object | None = None


_REMEMBER_SPEC = {
    "type": "function",
    "function": {
        "name": "remember",
        "description": (
            "PERSISTENTLY remember something about the server or a person (nickname, personality, "
            "way of speaking, rules, preferences) to use long-term later. Call when the user says "
            "'remember...', 'from now on call X...', or when you learn something worth remembering. "
            "Since notes live in the server's SHARED memory, when noting about the person speaking "
            "(me/I) use their REAL NAME in the note (e.g. 'Mike wants to be called ...') "
            "and DON'T write 'this user'/'this person'. IMPORTANT: if noting about someone @-mentioned "
            "in the message (there's a '<@id>' under 'Mentioned users'), INCLUDE their '<@id>' — e.g. "
            "'<@123> (Mike) has the nickname big mike' — so you can tag/address the right person later, not just plain text."
        ),
        "parameters": {
            "type": "object",
            "properties": {"note": {"type": "string", "description": "What to remember, brief"}},
            "required": ["note"],
        },
    },
}
_FORGET_SPEC = {
    "type": "function",
    "function": {
        "name": "forget",
        "description": (
            "FORGET/DELETE a note in SERVER MEMORY (nicknames, notes, saved rules). Call when the user "
            "says 'forget ...', 'delete the nickname ...', 'drop the note ...', 'stop remembering ...'. Pass "
            "'query' = keyword of the line to delete (e.g. 'big mike', 'john.doe'); deletes EVERY line containing it. "
            "WIPE the entire memory: user says 'delete all/wipe/forget everything' -> set all=true "
            "(NO query needed). NEVER use remember to write a line like 'deleted' — that's NOT "
            "deleting, it just clutters memory. The system reports back what was deleted."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword of the note to forget (leave empty if all=true)",
                },
                "all": {"type": "boolean", "description": "true = WIPE the entire server memory"},
            },
        },
    },
}
_WEB_SEARCH_SPEC = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Look up fresh/factual info on the internet. Use when you need facts beyond your knowledge. "
            "IMPORTANT: for prices/exchange rates/weather/CURRENT news, the query should only use 'today' or "
            "'latest' — NEVER append a specific NUMERIC DATE (e.g. '2/6/2026') to the query: it easily hits "
            "an article from a DIFFERENT date (e.g. '6/2') with STALE/WRONG prices. Good example: 'SJC gold price today'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (DON'T append a numeric date for current news)",
                }
            },
            "required": ["query"],
        },
    },
}
_READ_LINK_SPEC = {
    "type": "function",
    "function": {
        "name": "read_link",
        "description": (
            "Read the CONTENT of a specific link (URL) the user provides. Call when the user PASTES a link "
            "meaning 'read/summarize/what does this link say/what's in the link/check this article for me'. Pass the URL VERBATIM. "
            "(Different from web_search: web_search looks up by keyword; read_link opens that one exact link.)"
        ),
        "parameters": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "The link to read"}},
            "required": ["url"],
        },
    },
}
_SERVER_INFO_SPEC = {
    "type": "function",
    "function": {
        "name": "server_info",
        "description": "Info about the current Discord server.",
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["member_count", "roles", "channels"]}
            },
            "required": ["kind"],
        },
    },
}
_CURRENT_TIME_SPEC = {
    "type": "function",
    "function": {
        "name": "current_time",
        "description": "Current time and date (UTC).",
        "parameters": {"type": "object", "properties": {}},
    },
}
_CREATE_POLL_SPEC = {
    "type": "function",
    "function": {
        "name": "create_poll",
        "description": (
            "Create a real Discord poll in the channel. Call when the user wants to "
            "'create a poll', 'vote', 'poll', 'survey'. Split out the question + options yourself."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The poll question"},
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "The options (2-10 of them)",
                },
                "duration_hours": {
                    "type": "integer",
                    "description": "Hours the poll stays open (default 24, max 168 = 7 days)",
                },
                "multiple": {
                    "type": "boolean",
                    "description": "Whether to allow multiple answers (default false)",
                },
            },
            "required": ["question", "options"],
        },
    },
}


# AMBIGUOUS am/pm time rule — shared by remind + subscribe (both take a time from the user).
_AMBIG_TIME_RULE = (
    "EXTREMELY IMPORTANT ABOUT TIME: an hour from 1 to 12 that the user does NOT pair with "
    "'morning/noon/afternoon/evening' must ALWAYS be treated as AMBIGUOUS — EVEN if it looks like a "
    "valid 24h time. E.g. '11h15' could be 11:15 am OR 23:15 pm; '8h' could be 8 am OR 8 pm. In this "
    "case: NEVER call the tool, DON'T set it yourself, DON'T default to morning — ASK back exactly one "
    "question 'do you mean am or pm?' and wait for the reply. ONLY set it yourself (no asking) when: "
    "(a) there's a morning/noon/afternoon/evening word -> convert to 24h (11h15 evening=23:15, "
    "11h15 morning=11:15, 2 pm=14:00); OR (b) the hour >12 is already unambiguous (23h15, 14h); OR (c) it's "
    "relative ('in 5 minutes', 'in 2 hours')."
)


_REMIND_SPEC = {
    "type": "function",
    "function": {
        "name": "remind",
        "description": (
            "Set a reminder for the FUTURE. Call when the user says 'remind me...', "
            "'schedule...', 'alarm...', 'at X o'clock remind...'. Compute the ABSOLUTE time yourself based on "
            "'Now (Vietnam time)' ALREADY GIVEN in the prompt — DON'T call current_time, compute straight from it "
            "(e.g. 'tomorrow 5:30 pm', 'next Saturday 8h', 'in 2 hours'). "
            "Anyone @-mentioned in the message gets reminded too (if nobody is @'d, remind the commander). "
            "USE 'task' when the user wants to LOOK UP/REFRESH LIVE data and report it at the set time "
            "(e.g. 'at 5h show the gold price', 'tomorrow morning report the weather', 'tonight the USD rate'): set "
            "task='gold price today'… — at the time the bot will web search + answer with REAL figures. A normal personal "
            "thing (no lookup needed) -> SKIP task, just use message. " + _AMBIG_TIME_RULE
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "when": {
                    "type": "string",
                    "description": "Reminder time, format 'YYYY-MM-DD HH:MM' in VIETNAM TIME (24h)",
                },
                "message": {"type": "string", "description": "What to remind about"},
                "task": {
                    "type": "string",
                    "description": (
                        "OPTIONAL. Query to LOOK UP LIVE at the set time (e.g. 'gold price today'). "
                        "With task -> bot web searches + AI answers for real; empty -> just remind the message."
                    ),
                },
            },
            "required": ["when", "message"],
        },
    },
}


_LIST_REMINDERS_SPEC = {
    "type": "function",
    "function": {
        "name": "list_reminders",
        "description": (
            "List the commander's PENDING reminders, with time + content. "
            "Call when the user asks 'what reminders do I have', or when they want to delete one but it's unclear which (show them to pick)."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}
_CANCEL_REMINDER_SPEC = {
    "type": "function",
    "function": {
        "name": "cancel_reminder",
        "description": (
            "Cancel / delete a reminder that was set. Call when the user says 'delete reminder...', 'cancel alarm...'. "
            "'query' = keyword in the content or the time to find the right one (e.g. 'play game', '7 pm'). "
            "If MULTIPLE reminders match, the tool returns a list for you to ask the user to clarify — "
            "DON'T guess. Set 'all'=true ONLY when the user clearly wants to delete ALL. Only cancels their own reminders."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Content/time keyword to search (optional)",
                },
                "all": {
                    "type": "boolean",
                    "description": "true = cancel ALL of that person's reminders",
                },
            },
        },
    },
}
_EDIT_REMINDER_SPEC = {
    "type": "function",
    "function": {
        "name": "edit_reminder",
        "description": (
            "Edit a reminder that was set: change the TIME and/or CONTENT. Call when the user says 'move reminder ... to ...', "
            "'change reminder time ...', 'edit reminder ... to ...', 'shift reminder ... to ...'. When the user has CLEARLY stated "
            "which reminder + the new value, CALL this tool DIRECTLY (query=old keyword, when/message=new value), "
            "DON'T call list_reminders first. 'query' searches by content OR old time; if multiple match the tool "
            "returns a list to ask back. 'when'='YYYY-MM-DD HH:MM' (Vietnam time), 'message'=new content. "
            "At least one of when/message required."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keyword to find the reminder to edit"},
                "when": {
                    "type": "string",
                    "description": "New time 'YYYY-MM-DD HH:MM' (Vietnam time)",
                },
                "message": {"type": "string", "description": "New content"},
            },
            "required": ["query"],
        },
    },
}
_DELETE_POLL_SPEC = {
    "type": "function",
    "function": {
        "name": "delete_poll",
        "description": (
            "Delete the most recent poll the bot created in this channel. Call when the user says "
            "'delete poll', 'remove the poll', 'cancel the vote'."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}
_SUBSCRIBE_SPEC = {
    "type": "function",
    "function": {
        "name": "subscribe",
        "description": (
            "Subscribe to a DAILY RECURRING thing at a fixed time. Call when the user says 'every day...', "
            "'daily...', 'every morning/evening...', 'keep tracking for me...'. There are 2 KINDS — pick EXACTLY 1: "
            "(1) 'topic' = a subject that needs FRESH NEWS LOOKED UP + summarized (e.g. 'gold price', 'stock news', "
            "'Hanoi weather') — the bot web searches daily. These PHRASINGS are also a topic: 'clip news X "
            "for me', 'clip me the X news', 'news roundup of X', 'track X for me', 'update X' (when DAILY RECURRING); "
            "(2) 'message' = a recurring PERSONAL REMINDER, NO web lookup (e.g. 'every 5:30 ping me to go home' "
            "-> message='Time to head home!', 'every 8h take meds' -> message='Take your meds'). "
            "NEVER stuff a personal reminder into 'topic' (it'll web search and return junk). For a ONE-TIME reminder "
            "use 'remind', not this tool. " + _AMBIG_TIME_RULE
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Subject to LOOK UP daily (web search). Leave empty if using message.",
                },
                "message": {
                    "type": "string",
                    "description": "Recurring personal reminder (NO web lookup). Leave empty if using topic.",
                },
                "time": {
                    "type": "string",
                    "description": "Daily post time 'HH:MM' Vietnam time (default 08:00 if unspecified)",
                },
            },
        },
    },
}
_UNSUBSCRIBE_SPEC = {
    "type": "function",
    "function": {
        "name": "unsubscribe",
        "description": (
            "CANCEL/STOP a RUNNING recurring subscription. ONLY call when there's a clear intent to STOP — usually with "
            "a negation: 'stop ... anymore', 'quit ...', 'halt ...', 'unsubscribe ...', 'stop following', "
            "'turn off the ... news', 'no more ... updates'. If the subject is CLEAR, CALL DIRECTLY with 'query'=that subject "
            "(e.g. 'stop the stock news' -> query='stock'); if multiple match the tool lists them to ask back. "
            "'all'=true when cancelling ALL. NOTE: 'clip news X for me (daily)' is NOT a cancel — that's a SUBSCRIPTION, "
            "use subscribe. Only treat it as a cancel when there's a stop/negation word above."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Subject keyword (optional)"},
                "all": {
                    "type": "boolean",
                    "description": "true = cancel ALL of that person's subscriptions",
                },
            },
        },
    },
}
_EDIT_SUBSCRIPTION_SPEC = {
    "type": "function",
    "function": {
        "name": "edit_subscription",
        "description": (
            "Edit a news subscription: change the post TIME and/or the SUBJECT. Call when the user says 'change the update time of ... "
            "to ...', 'edit subscription ...', 'shift the ... news to time ...', 'change the ... news to ...'. When "
            "the user has CLEARLY stated which subscription + the new value, CALL this tool DIRECTLY (query=old subject, time/topic=new "
            "value), DON'T call list_subscriptions first. If multiple match the tool returns a list to ask "
            "back. 'time'='HH:MM' (Vietnam time), 'topic'=new subject. At least one of time/topic required."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Subject keyword to find the subscription to edit",
                },
                "time": {"type": "string", "description": "New time 'HH:MM' Vietnam time"},
                "topic": {"type": "string", "description": "New subject"},
            },
            "required": ["query"],
        },
    },
}
_LIST_SUBSCRIPTIONS_SPEC = {
    "type": "function",
    "function": {
        "name": "list_subscriptions",
        "description": (
            "List the commander's ACTIVE recurring news subscriptions (subject + time). "
            "Call when the user asks 'what am I following', or when they want to cancel but it's unclear which."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}


def tool_specs(has_search: bool, include_actions: bool = False) -> list[dict]:
    specs = [
        _REMEMBER_SPEC,
        _FORGET_SPEC,
        _REMIND_SPEC,
        _LIST_REMINDERS_SPEC,
        _CANCEL_REMINDER_SPEC,
        _EDIT_REMINDER_SPEC,
        _CREATE_POLL_SPEC,
        _DELETE_POLL_SPEC,
        _SUBSCRIBE_SPEC,
        _UNSUBSCRIBE_SPEC,
        _EDIT_SUBSCRIPTION_SPEC,
        _LIST_SUBSCRIPTIONS_SPEC,
        _SERVER_INFO_SPEC,
        _CURRENT_TIME_SPEC,
    ]
    if has_search:
        # read_link goes with web_search (same web-tool group): keyword lookup + reading a specific link.
        specs = [_WEB_SEARCH_SPEC, _READ_LINK_SPEC, *specs]
    if include_actions:
        from app.services.ai.actions.registry import ACTION_SPECS  # lazy: avoid import cycle

        specs = [*specs, *ACTION_SPECS]
    return specs


def parse_args(raw: str | None) -> dict:
    try:
        return json.loads(raw or "{}")
    except (ValueError, TypeError):
        return {}


def _parse_vn_to_utc(when_raw: str) -> datetime | None:
    """Vietnam-time string (computed by the model) -> tz-aware UTC datetime. None if unparseable."""
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            naive = datetime.strptime(when_raw, fmt)
            return naive.replace(tzinfo=VN_TZ).astimezone(UTC)
        except ValueError:
            continue
    try:  # fallback: any ISO
        dt = datetime.fromisoformat(when_raw)
        return (dt.replace(tzinfo=VN_TZ) if dt.tzinfo is None else dt).astimezone(UTC)
    except ValueError:
        return None


def _vn_remind_at(r) -> datetime:
    """remind_at (UTC, possibly naive from SQLite) -> Vietnam-time datetime."""
    dt = r.remind_at if r.remind_at.tzinfo is not None else r.remind_at.replace(tzinfo=UTC)
    return dt.astimezone(VN_TZ)


def _fmt_reminder(r) -> str:
    """One line for the reader: 'HH:MM dd/mm — content'."""
    return f"{_vn_remind_at(r).strftime('%H:%M %d/%m')} — {r.message}"


def _period(h: int) -> str:
    """Rough time-of-day label by hour, so a query like 'evening' can match a reminder.
    Used by _reminder_haystack to let users cancel/edit a reminder by typing the time of day."""
    if 5 <= h <= 11:
        return "morning"
    if h == 12:
        return "noon"
    if 13 <= h <= 17:
        return "afternoon"
    if 18 <= h <= 21:
        return "evening"
    return "night"


def _reminder_haystack(r) -> str:
    """Combine CONTENT + several TIME variants (24h, 12h am/pm, time-of-day, date) to match the
    user's query — allows deleting by '7pm', '7 pm', '19h', '19:00', 'evening' or by content. All lowercased."""
    dt = _vn_remind_at(r)
    h, h12 = dt.hour, (dt.hour % 12 or 12)
    ampm = "pm" if h >= 12 else "am"
    period = _period(h)
    variants = [
        dt.strftime("%H:%M"),  # 19:00
        f"{h}h",  # 19h
        f"{h12}{ampm}",  # 7pm
        f"{h12} {ampm}",  # 7 pm
        f"{h12}h",  # 7h
        period,  # evening
        dt.strftime("%d/%m"),
    ]
    return f"{r.message or ''} {' '.join(variants)}".lower()


async def _my_pending(ctx: ToolContext) -> list:
    """The commander's OWN pending reminders."""
    rows = await ctx.reminder_repo.pending_for_guild(ctx.guild_pk)
    return [r for r in rows if r.creator_id == (ctx.commander_id or 0)]


async def _list_reminders(ctx: ToolContext) -> str:
    """List the commander's pending reminders — so they can see & pick which to delete."""
    if ctx.reminder_repo is None or ctx.guild_pk is None:
        return "Can't view yet (missing context)."
    mine = await _my_pending(ctx)
    if not mine:
        return "You have no pending reminders."
    lines = "\n".join(f"{i + 1}. {_fmt_reminder(r)}" for i, r in enumerate(mine))
    return f"Your pending reminders:\n{lines}"


async def _cancel_reminder(args: dict, ctx: ToolContext) -> str:
    """Cancel the commander's OWN reminders. Multiple match -> LIST and ask back (don't delete the wrong one).
    all=true -> delete all. empty query + still many -> also list to pick."""
    if ctx.reminder_repo is None or ctx.guild_pk is None:
        return "Can't cancel yet (missing context)."
    mine = await _my_pending(ctx)
    if not mine:
        return "You have no pending reminders."
    if bool(args.get("all")):
        for r in mine:
            await ctx.reminder_repo.cancel(r.id, ctx.guild_pk)
        return f"Cancelled all {len(mine)} reminders."
    query = str(args.get("query", "")).strip().lower()
    # Match query in CONTENT or TIME (19:00 / 19h / 7pm / evening...). Empty -> take all.
    matched = [r for r in mine if query in _reminder_haystack(r)] if query else mine
    if not matched:
        lines = "\n".join(f"- {_fmt_reminder(r)}" for r in mine)
        return f"No reminder matched '{query}'. You currently have:\n{lines}"
    if len(matched) > 1:
        # Ambiguous -> list it, let the model ask the user to clarify, DON'T delete blindly.
        lines = "\n".join(f"- {_fmt_reminder(r)}" for r in matched)
        return f"{len(matched)} reminders match, be more specific (by time or content):\n{lines}"
    await ctx.reminder_repo.cancel(matched[0].id, ctx.guild_pk)
    return f"Cancelled reminder: {_fmt_reminder(matched[0])}"


async def _edit_reminder(args: dict, ctx: ToolContext) -> str:
    """Edit the time/content of one of the commander's reminders. Multiple match -> list and ask back."""
    if ctx.reminder_repo is None or ctx.guild_pk is None:
        return "Can't edit yet (missing context)."
    mine = await _my_pending(ctx)
    if not mine:
        return "You have no pending reminders."
    query = str(args.get("query", "")).strip().lower()
    matched = [r for r in mine if query in _reminder_haystack(r)] if query else mine
    if not matched:
        lines = "\n".join(f"- {_fmt_reminder(r)}" for r in mine)
        return f"No reminder matched '{query}'. You currently have:\n{lines}"
    if len(matched) > 1:
        lines = "\n".join(f"- {_fmt_reminder(r)}" for r in matched)
        return f"{len(matched)} reminders match, please be more specific:\n{lines}"
    new_when = str(args.get("when", "")).strip()
    new_msg = str(args.get("message", "")).strip()
    if not new_when and not new_msg:
        return "Need a new time or new content to edit."
    remind_at = None
    if new_when:
        remind_at = _parse_vn_to_utc(new_when)
        if remind_at is None:
            return "Don't understand the new time — give it as 'YYYY-MM-DD HH:MM' (Vietnam time)."
        if remind_at <= datetime.now(UTC):
            return "The new time has already passed, pick a time in the future."
    updated = await ctx.reminder_repo.update_reminder(
        matched[0].id, ctx.guild_pk, remind_at=remind_at, message=(new_msg or None)
    )
    if updated is None:
        return "Couldn't edit that reminder."
    return f"Updated reminder: {_fmt_reminder(updated)}"


async def _create_reminder(args: dict, ctx: ToolContext) -> str:
    """Write a reminder to the DB (via ctx.reminder_repo). The model already computed 'when' in Vietnam time."""
    if ctx.reminder_repo is None or ctx.guild_pk is None or ctx.channel_id is None:
        return "Can't set the reminder yet (missing context)."
    when_raw = str(args.get("when", "")).strip()
    message = str(args.get("message", "")).strip()
    # task (optional): query to LOOK UP LIVE at the set time (smart reminder). Empty -> None.
    task = str(args.get("task", "")).strip() or None
    if not when_raw or not message:
        return "Need both a time and reminder content."
    remind_at = _parse_vn_to_utc(when_raw)
    if remind_at is None:
        return "I don't understand the time — give it as 'YYYY-MM-DD HH:MM' (Vietnam time)."
    if remind_at <= datetime.now(UTC):
        return "That time has already passed, pick a time in the future."
    targets = list(ctx.target_user_ids) or ([ctx.commander_id] if ctx.commander_id else [])
    await ctx.reminder_repo.create(
        guild_id=ctx.guild_pk,
        channel_id=ctx.channel_id,
        creator_id=ctx.commander_id or 0,
        target_ids=targets,
        message=message,
        remind_at=remind_at,
        task=task,
    )
    if task:
        return f"Scheduled at {when_raw} (Vietnam time) to look up '{task}' and report the real result to you."
    return f"Reminder set for {when_raw} (Vietnam time): {message}"


def _parse_hhmm(raw: str, default: tuple = (8, 0)) -> tuple:
    """'HH:MM' / '8h' / '8h30' / '8am' / '8:30pm' (Vietnam time) -> (hour, minute).
    Unparseable -> default (08:00)."""
    raw = (raw or "").strip().lower().replace("o'clock", "").replace(" ", "")
    ampm = None
    if raw.endswith("am"):
        ampm, raw = "am", raw[:-2]
    elif raw.endswith("pm"):
        ampm, raw = "pm", raw[:-2]
    for fmt in ("%H:%M", "%Hh%M", "%Hh", "%H"):
        try:
            t = datetime.strptime(raw, fmt)
            hour = t.hour
            if ampm == "pm" and hour < 12:  # 1-11 pm -> 13-23
                hour += 12
            elif ampm == "am" and hour == 12:  # 12 am -> midnight
                hour = 0
            return hour, t.minute
        except ValueError:
            continue
    return default


async def _subscribe(args: dict, ctx: ToolContext) -> str:
    """Create a daily news subscription. If the scheduled time already passed today -> start TOMORROW."""
    if ctx.subscription_repo is None or ctx.guild_pk is None or ctx.channel_id is None:
        return "Can't subscribe yet (missing context)."
    topic = str(args.get("topic", "")).strip() or None
    message = str(args.get("message", "")).strip() or None
    if not topic and not message:
        return "Need a news subject (topic) OR a recurring reminder (message)."
    if (
        topic and message
    ):  # the 2 kinds are mutually exclusive -> prefer message (personal reminder is clearer intent)
        topic = None
    hour, minute = _parse_hhmm(str(args.get("time", "")))
    now_vn = datetime.now(VN_TZ)
    # Scheduled time already passed today -> mark as run today so the first one is TOMORROW (avoid firing immediately).
    last_run_on = now_vn.date() if (hour, minute) <= (now_vn.hour, now_vn.minute) else None
    await ctx.subscription_repo.create(
        guild_id=ctx.guild_pk,
        channel_id=ctx.channel_id,
        creator_id=ctx.commander_id or 0,
        topic=topic,
        message=message,
        hour=hour,
        minute=minute,
        last_run_on=last_run_on,
    )
    what = f"update '{topic}'" if topic else f"ping: '{message}'"
    return f"Subscribed: every day at {hour:02d}:{minute:02d} {what}."


async def _my_subs(ctx: ToolContext) -> list:
    return await ctx.subscription_repo.active_for_creator(ctx.guild_pk, ctx.commander_id or 0)


def _sub_label(s) -> str:
    """Label for one subscription for display/matching: subject (news kind) OR reminder (personal kind)."""
    return (getattr(s, "topic", None) or getattr(s, "message", None) or "(empty)").strip()


async def _list_subscriptions(ctx: ToolContext) -> str:
    if ctx.subscription_repo is None or ctx.guild_pk is None:
        return "Can't view yet (missing context)."
    mine = await _my_subs(ctx)
    if not mine:
        return "You don't have any recurring news subscriptions yet."
    lines = "\n".join(
        f"{i + 1}. {s.hour:02d}:{s.minute:02d} — {_sub_label(s)}" for i, s in enumerate(mine)
    )
    return f"Your recurring subscriptions:\n{lines}"


async def _unsubscribe(args: dict, ctx: ToolContext) -> str:
    """Cancel the commander's OWN subscriptions. Multiple match -> list and ask back; all=true -> cancel all."""
    if ctx.subscription_repo is None or ctx.guild_pk is None:
        return "Can't cancel yet (missing context)."
    mine = await _my_subs(ctx)
    if not mine:
        return "You have no active subscriptions."
    if bool(args.get("all")):
        for s in mine:
            await ctx.subscription_repo.cancel(s.id, ctx.guild_pk)
        return f"Cancelled all {len(mine)} subscriptions."
    query = str(args.get("query", "")).strip().lower()
    matched = [s for s in mine if query in _sub_label(s).lower()] if query else mine
    if not matched:
        lines = "\n".join(f"- {_sub_label(s)} ({s.hour:02d}:{s.minute:02d})" for s in mine)
        return f"No subscription matched '{query}'. You currently have:\n{lines}"
    if len(matched) > 1:
        lines = "\n".join(f"- {_sub_label(s)} ({s.hour:02d}:{s.minute:02d})" for s in matched)
        return f"{len(matched)} subscriptions match, please say which one:\n{lines}"
    await ctx.subscription_repo.cancel(matched[0].id, ctx.guild_pk)
    return f"Cancelled subscription: {_sub_label(matched[0])}"


async def _edit_subscription(args: dict, ctx: ToolContext) -> str:
    """Edit the time/subject of one of the commander's subscriptions. Multiple match -> list and ask back.
    Changing the time -> reset last_run_on so the new schedule takes effect (no waiting until tomorrow)."""
    if ctx.subscription_repo is None or ctx.guild_pk is None:
        return "Can't edit yet (missing context)."
    mine = await _my_subs(ctx)
    if not mine:
        return "You have no active subscriptions."
    query = str(args.get("query", "")).strip().lower()
    matched = [s for s in mine if query in _sub_label(s).lower()] if query else mine
    if not matched:
        lines = "\n".join(f"- {_sub_label(s)} ({s.hour:02d}:{s.minute:02d})" for s in mine)
        return f"No subscription matched '{query}'. You currently have:\n{lines}"
    if len(matched) > 1:
        lines = "\n".join(f"- {_sub_label(s)} ({s.hour:02d}:{s.minute:02d})" for s in matched)
        return f"{len(matched)} subscriptions match, please say which one:\n{lines}"
    new_time = str(args.get("time", "")).strip()
    new_topic = str(args.get("topic", "")).strip()
    if not new_time and not new_topic:
        return "Need a new time or new content to edit."
    kwargs: dict = {}
    if new_topic:
        # Apply the new content to the RIGHT kind of subscription: news -> topic, personal reminder -> message.
        if matched[0].topic is not None:
            kwargs["topic"] = new_topic
        else:
            kwargs["message"] = new_topic
    if new_time:
        hour, minute = _parse_hhmm(new_time)
        kwargs["hour"], kwargs["minute"] = hour, minute
        now_vn = datetime.now(VN_TZ)
        # Time changed -> reset last_run_on: if the new time is still ahead today run today, else tomorrow.
        kwargs["last_run_on"] = (
            None if (hour, minute) > (now_vn.hour, now_vn.minute) else now_vn.date()
        )
    updated = await ctx.subscription_repo.update(matched[0].id, ctx.guild_pk, **kwargs)
    if updated is None:
        return "Couldn't edit that subscription."
    return f"Updated: every day at {updated.hour:02d}:{updated.minute:02d} — {_sub_label(updated)}."


def _stage_poll(args: dict, ctx: ToolContext) -> str:
    """Validate the poll args then queue into ctx.pending for the cog to send a real Discord poll to the channel."""
    from app.services.ai.actions.registry import PendingAction  # lazy: avoid import cycle

    question = str(args.get("question", "")).strip()
    options = [str(o).strip() for o in (args.get("options") or []) if str(o).strip()]
    if not question:
        return "Missing the poll question."
    if not (2 <= len(options) <= 10):
        return "A poll needs 2-10 options."
    dur = args.get("duration_hours")
    dur = dur if isinstance(dur, int) and 1 <= dur <= 168 else 24  # 1h..7 days, default 24h
    ctx.pending.append(
        PendingAction(
            "create_poll",
            False,  # creating a poll isn't a destructive action -> no confirm button needed
            f"Poll: {question}",
            {
                "question": question,
                "options": options,
                "duration_hours": dur,
                "multiple": bool(args.get("multiple")),
            },
        )
    )
    return f"Poll created: {question} ({len(options)} options)."


async def execute(name: str, args: dict, ctx: ToolContext) -> str:
    log.info("agent tool call: name=%s args=%s", name, args)
    if name == "remember":
        note = str(args.get("note", ""))
        if ctx.memory_repo_doc is not None and ctx.guild_pk is not None and note.strip():
            await ctx.memory_repo_doc.append_note(ctx.guild_pk, note)
            return "Noted."
        return "Couldn't remember that."
    if name == "forget":
        if ctx.memory_repo_doc is None or ctx.guild_pk is None:
            return "Can't delete yet (missing context)."
        if bool(args.get("all")):
            # WIPE = nuclear -> needs Manage Server permission (like /claw-lore-clear).
            if not ctx.commander_perms.get("manage_guild"):
                return "You need the Manage Server permission to wipe the entire server memory."
            await ctx.memory_repo_doc.clear(ctx.guild_pk)
            return "Wiped the entire server memory."
        query = str(args.get("query", "")).strip()
        if not query:
            return "Not sure what to forget — give a keyword, or say 'delete all' (all) to wipe everything."
        removed = await ctx.memory_repo_doc.remove_notes(ctx.guild_pk, query)
        if not removed:
            return f"No note matched '{query}' to forget."
        return "Forgot: " + "; ".join(removed)
    if name == "remind":
        return await _create_reminder(args, ctx)
    if name == "list_reminders":
        return await _list_reminders(ctx)
    if name == "cancel_reminder":
        return await _cancel_reminder(args, ctx)
    if name == "edit_reminder":
        return await _edit_reminder(args, ctx)
    if name == "create_poll":
        return _stage_poll(args, ctx)
    if name == "delete_poll":
        from app.services.ai.actions.registry import PendingAction  # lazy: avoid import cycle

        ctx.pending.append(PendingAction("delete_poll", False, "Delete the most recent poll", {}))
        return "Deleted the most recent poll."
    if name == "subscribe":
        return await _subscribe(args, ctx)
    if name == "unsubscribe":
        return await _unsubscribe(args, ctx)
    if name == "edit_subscription":
        return await _edit_subscription(args, ctx)
    if name == "list_subscriptions":
        return await _list_subscriptions(ctx)
    if name == "web_search":
        return await run_web_search(str(args.get("query", "")))
    if name == "read_link":
        return await run_read_link(str(args.get("url", "")))
    if name == "server_info":
        return run_server_info(str(args.get("kind", "")), ctx.guild_snapshot)
    if name == "current_time":
        return run_current_time()
    # Action tools (sub-project 3): only STAGE (validate) + queue into ctx.pending; the cog executes later.
    from app.services.ai.actions.registry import ACTION_PERMS, stage  # lazy

    if name in ACTION_PERMS:
        res = await stage(name, args, ctx)
        if isinstance(res, str):
            log.info("agent action stage rejected: name=%s -> %s", name, res)
            return res  # error/rejection -> report back to the model
        ctx.pending.append(res)
        log.info("agent action staged: name=%s desc=%s", name, res.description)
        # DESTRUCTIVE action -> wait for the ✅/❌ button. Safe action -> the system does it NOW (no confirm).
        # Report it correctly so the model doesn't wrongly say "waiting for admin confirm" for a self-running one.
        if res.destructive:
            return f"Queued: {res.description}. The system will show ✅/❌ buttons for an admin to confirm."
        return f"Done: {res.description}."
    log.info("agent tool called: name=%s", name)
    return f"Tool doesn't exist: {name}"
