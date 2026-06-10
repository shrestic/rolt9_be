"""Claw Agent Actions — stage (validate) + execute server actions.

Action tools in the tool-loop only STAGE (validate + create a PendingAction). The cog then executes:
safe actions run immediately, DESTRUCTIVE actions (ban/kick/timeout/delete_role) wait for the ✅ button.
Gated per-action by the commander's Discord permissions; the bot must have enough permission + role rank.
"""

import logging
from dataclasses import dataclass, field
from datetime import timedelta

from app.repositories.ai_config import AIConfigRepository
from app.repositories.currency_config import CurrencyConfigRepository
from app.repositories.guild import GuildRepository
from app.repositories.karma_config import KarmaConfigRepository
from app.repositories.leveling_config import GuildLevelingConfigRepository
from app.repositories.minigame_config import MinigameConfigRepository
from app.repositories.welcome_config import WelcomeConfigRepository

log = logging.getLogger(__name__)


@dataclass
class PendingAction:
    kind: str
    destructive: bool
    description: str
    params: dict = field(default_factory=dict)


# action kind -> the Discord permission flag the commander must have
ACTION_PERMS = {
    "create_role": "manage_roles",
    "assign_role": "manage_roles",
    "remove_role": "manage_roles",
    "delete_role": "manage_roles",
    "toggle_plugin": "manage_guild",
    "kick": "kick_members",
    "ban": "ban_members",
    "unban": "ban_members",
    "timeout": "moderate_members",
    "untimeout": "moderate_members",
}
# DESTRUCTIVE actions need the ✅ confirm button. unban/untimeout are RESTORING actions
# (removing a punishment) so NOT destructive → run immediately, no confirm needed.
DESTRUCTIVE = {"delete_role", "kick", "ban", "timeout"}

# plugin name -> (RepoClass, field). Every repo has upsert(guild_id, data).
PLUGIN_TOGGLES = {
    "leveling": (GuildLevelingConfigRepository, "enabled"),
    "currency": (CurrencyConfigRepository, "enabled"),
    "welcome": (WelcomeConfigRepository, "enabled"),
    "minigame": (MinigameConfigRepository, "enabled"),
    "karma": (KarmaConfigRepository, "enabled"),
    "ai": (AIConfigRepository, "enabled"),
    "agent": (AIConfigRepository, "agent_enabled"),
    "tools": (AIConfigRepository, "tools_enabled"),
}

_PERM_LABEL = {
    "manage_roles": "Manage Roles",
    "manage_guild": "Manage Guild",
    "kick_members": "Kick Members",
    "ban_members": "Ban Members",
    "moderate_members": "Moderate Members",
}

ACTION_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "create_role",
            "description": "Create a new role in the server.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "color": {"type": "string", "description": "Hex code #rrggbb (optional)"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "assign_role",
            "description": "Assign a role to the @-mentioned user(s), or to the commander themselves if nobody is mentioned.",
            "parameters": {
                "type": "object",
                "properties": {"role_name": {"type": "string"}},
                "required": ["role_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_role",
            "description": "Remove a role from the @-mentioned user(s), or from the commander themselves.",
            "parameters": {
                "type": "object",
                "properties": {"role_name": {"type": "string"}},
                "required": ["role_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_role",
            "description": "Delete a role from the server (destructive action, needs confirmation).",
            "parameters": {
                "type": "object",
                "properties": {"role_name": {"type": "string"}},
                "required": ["role_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "toggle_plugin",
            "description": "Enable or disable one of the bot's plugins.",
            "parameters": {
                "type": "object",
                "properties": {
                    "plugin": {"type": "string", "enum": list(PLUGIN_TOGGLES)},
                    "enabled": {"type": "boolean"},
                },
                "required": ["plugin", "enabled"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kick",
            "description": (
                "Kick user(s) from the server (destructive action, needs confirmation). The target is whoever "
                "is @-mentioned in the message; if the user types a NAME without a real mention, pass 'user'=name/ID."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user": {
                        "type": "string",
                        "description": "Name/ID when @-mention isn't possible",
                    },
                    "reason": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ban",
            "description": (
                "Ban user(s) from the server (destructive action, needs confirmation). The target is whoever "
                "is @-mentioned in the message; if the user types a NAME without a real mention, pass 'user'=name/ID."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user": {
                        "type": "string",
                        "description": "Name/ID when @-mention isn't possible",
                    },
                    "reason": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "timeout",
            "description": (
                "Timeout / temporarily mute (block from chatting) a user (destructive action, needs confirmation). The target "
                "is whoever is @'d; if the user types a NAME without a real mention, pass 'user'=name/ID. "
                "DON'T ask back for the number of minutes — if the user doesn't say, DEFAULT to 10 minutes and just call the tool."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "minutes": {"type": "integer", "description": "Number of minutes (empty = 10)"},
                    "user": {
                        "type": "string",
                        "description": "Name/ID when @-mention isn't possible",
                    },
                    "reason": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "untimeout",
            "description": (
                "Remove a timeout / unmute a user — let them chat again right away. Call IMMEDIATELY when the user says "
                "'remove mute', 'unmute', 'lift the timeout', 'open X's mouth', 'let X talk again', 'let X off'. "
                "The target is whoever is @'d; if they type a NAME without an @, pass 'user'=name/ID. "
                "DON'T just reply in words — you must call the tool."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user": {
                        "type": "string",
                        "description": "Name/ID when @-mention isn't possible",
                    },
                    "reason": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "unban",
            "description": (
                "Unban a user. Since a banned person has LEFT the server (can't be @'d), "
                "pass 'user' as their NAME or ID; if they can still be @'d, the bot uses the mentioned person."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user": {"type": "string", "description": "Name or ID of the person to unban"},
                    "reason": {"type": "string"},
                },
            },
        },
    },
]


def _parse_color(raw):
    """Hex '#rrggbb' -> int, or None if unparseable."""
    if not raw:
        return None
    s = str(raw).strip().lstrip("#")
    try:
        return int(s, 16)
    except ValueError:
        return None


def _find_role_name(role_name: str, role_names: list[str]) -> str | None:
    low = role_name.strip().lower()
    for r in role_names:
        if r.lower() == low:
            return r
    return None


def _resolve_member_ids(guild, target_ids, query) -> "tuple[list[int], str | None]":
    """Find the member id(s) to act on. With a mention (target_ids) -> use it directly; otherwise LOOK UP BY NAME/ID
    in the member list (e.g. user typed '@samnguyen' as text, no real mention).
    Returns (ids, error): error != None means not found or ambiguous -> report back to the user."""
    ids = [int(x) for x in (target_ids or [])]
    if ids:
        return ids, None
    q = (query or "").strip().lower().lstrip("@")
    if not q:
        return [], None  # caller decides (e.g. assign falls back to the commander)
    # ALLOW matching other BOTS (e.g. ban 'Jockie Music' = a music bot — a legitimate need); only
    # exclude rolt9 ITSELF (don't ban yourself). Previously every bot was excluded -> banning any bot was "not found".
    me_id = getattr(getattr(guild, "me", None), "id", None)
    cands = [
        m
        for m in getattr(guild, "members", [])
        if m.id != me_id
        and (
            q == str(m.id)
            or q in (m.name or "").lower()
            or q in (getattr(m, "display_name", "") or "").lower()
        )
    ]
    if not cands:
        return (
            [],
            f"Couldn't find anyone named '{query}' in the server — try @-mentioning directly.",
        )
    if len(cands) > 1:
        names = ", ".join(getattr(m, "display_name", str(m.id)) for m in cands[:5])
        return [], f"{len(cands)} people match '{query}' ({names}). @ the right one to be sure."
    return [cands[0].id], None


async def stage(name: str, args: dict, ctx) -> "PendingAction | str":
    """Validate + permission-gate. Returns a PendingAction (awaiting cog execute) or an error string for the model."""
    perm = ACTION_PERMS.get(name)
    if perm is None:
        return f"Unsupported action: {name}"
    if not ctx.commander_perms.get(perm):
        return f"You need the {_PERM_LABEL.get(perm, perm)} permission to do this."

    destructive = name in DESTRUCTIVE

    if name == "create_role":
        rn = str(args.get("name", "")).strip()
        if not rn or len(rn) > 100:
            return "Invalid role name (1-100 characters)."
        color = _parse_color(args.get("color"))
        return PendingAction(
            name, destructive, f"Create role **{rn}**", {"name": rn, "color": color}
        )

    if name in ("assign_role", "remove_role", "delete_role"):
        rn = str(args.get("role_name", "")).strip()
        if not rn:
            return "Missing role name."
        match = _find_role_name(rn, ctx.role_names)
        # assign_role ALLOWS a not-yet-existing role: it may be created by create_role in the SAME pass
        # (the cog runs create before assign). Real existence is checked at execute. remove/delete
        # need an existing role -> still reject early for clarity.
        if match is None and name != "assign_role":
            return f"Couldn't find role '{rn}' in the server."
        role_label = match or rn
        if name == "delete_role":
            return PendingAction(
                name, destructive, f"Delete role **{role_label}**", {"role_name": role_label}
            )
        targets = list(ctx.target_user_ids) or ([ctx.commander_id] if ctx.commander_id else [])
        if not targets:
            return "Not sure who to assign/remove for."
        verb = "Assign" if name == "assign_role" else "Remove"
        return PendingAction(
            name,
            destructive,
            f"{verb} role **{role_label}** for {len(targets)} people",
            {"role_name": role_label, "target_ids": targets},
        )

    if name == "toggle_plugin":
        plugin = str(args.get("plugin", "")).strip().lower()
        if plugin not in PLUGIN_TOGGLES:
            return f"Invalid plugin. Valid: {', '.join(PLUGIN_TOGGLES)}"
        enabled = bool(args.get("enabled"))
        return PendingAction(
            name,
            destructive,
            f"{'Enable' if enabled else 'Disable'} plugin **{plugin}**",
            {"plugin": plugin, "enabled": enabled},
        )

    if name in ("kick", "ban", "timeout"):
        targets = list(ctx.target_user_ids)
        # Allow naming a NAME/ID when the user typed '@name' as text (no real mention) -> execute finds the member.
        query = str(args.get("user", "") or "").strip()
        if not targets and not query:
            return f"Need to @ the person to {name} (or give a name/ID if you can't @ them)."
        # SERVER OWNER: Discord forbids ban/kick/timeout on the owner -> reject RIGHT at stage (don't show the
        # confirm button only to report it later). Can only block when an id exists (mention); a bare name -> execute blocks it too.
        owner_id = (ctx.guild_snapshot or {}).get("owner_id")
        if owner_id is not None and any(int(t) == int(owner_id) for t in targets):
            return f"Can't {name} the server owner (Discord forbids it) — skipping."
        params = {
            "target_ids": targets,
            "query": query,
            "reason": str(args.get("reason", "") or ""),
        }
        who = f"{len(targets)} people" if targets else f"'{query}'"
        if name == "timeout":
            minutes = args.get("minutes")
            # Not specified/invalid -> default 10 minutes (avoids asking back = avoids the multi-turn trap).
            if not isinstance(minutes, int) or minutes <= 0:
                minutes = 10
            params["minutes"] = minutes
            desc = f"Timeout {who} for {minutes} minutes"
        else:
            desc = f"{name.capitalize()} {who}"
        return PendingAction(name, destructive, desc, params)

    if name == "untimeout":
        # Remove mute: the person is still in the server. Allow naming a name/ID if @-mention isn't possible.
        targets = list(ctx.target_user_ids)
        query = str(args.get("user", "") or "").strip()
        if not targets and not query:
            return "Need to @ the person to remove the timeout/unmute (or give a name/ID)."
        who = f"{len(targets)} people" if targets else f"'{query}'"
        return PendingAction(
            name,
            False,
            f"Remove timeout for {who}",
            {"target_ids": targets, "query": query, "reason": str(args.get("reason", "") or "")},
        )

    if name == "unban":
        # The banned person has left the server → prefer lookup by name/ID ('user'); a mention (if any) is also accepted.
        targets = list(ctx.target_user_ids)
        query = str(args.get("user", "") or "").strip()
        if not targets and not query:
            return "Need to enter the NAME or ID of the person to unban (they've left the server so can't be @'d)."
        return PendingAction(
            name,
            False,
            f"Unban: {query or f'{len(targets)} people'}",
            {"target_ids": targets, "query": query, "reason": str(args.get("reason", "") or "")},
        )

    return f"Unsupported action: {name}"


async def execute(pending: PendingAction, *, guild, session, channel=None) -> str:
    """Actually execute. guild = discord.Guild; session = AsyncSession; channel = the channel to send to
    (needed for polls). On error -> a report string."""
    import datetime

    import discord

    p = pending.params
    try:
        if pending.kind == "create_poll":
            if channel is None:
                return "Couldn't send the poll (missing channel)."
            poll = discord.Poll(
                question=p["question"],
                duration=datetime.timedelta(hours=p["duration_hours"]),
                multiple=p["multiple"],
            )
            for opt in p["options"]:
                poll.add_answer(text=opt[:55])  # Discord limits 55 chars/answer
            await channel.send(poll=poll)
            return f"Poll created: {p['question']}"

        if pending.kind == "delete_poll":
            if channel is None:
                return "Couldn't delete the poll (missing channel)."
            me_id = guild.me.id if guild is not None and guild.me is not None else None
            # Scan a few recent messages, find a poll CREATED BY THE BOT to delete (deleting the message = deleting the poll).
            async for m in channel.history(limit=30):
                if getattr(m, "poll", None) is not None and (
                    me_id is None or getattr(m.author, "id", None) == me_id
                ):
                    await m.delete()
                    return "Deleted the most recent poll."
            return "No recent poll found to delete."

        if pending.kind == "create_role":
            kwargs = {"name": p["name"]}
            if p.get("color") is not None:
                kwargs["colour"] = discord.Colour(p["color"])
            await guild.create_role(**kwargs)
            return f"Created role {p['name']}."

        if pending.kind in ("assign_role", "remove_role", "delete_role"):
            role = discord.utils.find(
                lambda r: r.name.lower() == p["role_name"].lower(), guild.roles
            )
            if role is None:
                return f"Role {p['role_name']} no longer exists."
            if guild.me.top_role <= role:
                return f"Role {role.name} is above/equal to the bot's role — can't operate on it."
            if pending.kind == "delete_role":
                await role.delete()
                return f"Deleted role {role.name}."
            done = 0
            for uid in p["target_ids"]:
                member = guild.get_member(uid)
                if member is None:
                    continue
                if pending.kind == "assign_role":
                    await member.add_roles(role)
                else:
                    await member.remove_roles(role)
                done += 1
            verb = "assigned" if pending.kind == "assign_role" else "removed"
            return f"{verb.capitalize()} role {role.name} for {done} people."

        if pending.kind in ("kick", "ban", "timeout"):
            # With a mention -> use it; otherwise find the member by name/ID (typed "@samnguyen" as text).
            target_ids, err = _resolve_member_ids(guild, p.get("target_ids"), p.get("query"))
            if err:
                return err
            if not target_ids:
                return f"Not sure who to {pending.kind}."
            done = 0
            blocked: list[
                str
            ] = []  # people with role ≥ bot — skip them, DON'T block the whole batch
            owner_id = getattr(guild, "owner_id", None)
            failed: list[str] = []  # Discord rejected (Forbidden…) at execute time
            for uid in target_ids:
                member = guild.get_member(uid)
                # SERVER OWNER: Discord forbids ban/kick/timeout on the owner REGARDLESS of role -> block clearly, don't let
                # guild.ban(owner) throw Forbidden and crash (this is the 'ban shrestic' = server owner case).
                if member is not None and owner_id is not None and member.id == owner_id:
                    blocked.append(f"{member.display_name} (server owner)")
                    continue
                # Rank: only block when the member is still in the server and role ≥ bot.
                if member is not None and guild.me.top_role <= member.top_role:
                    blocked.append(member.display_name)
                    continue
                try:
                    if pending.kind == "ban":
                        # Can ban EVEN people who left the server (ban by ID via discord.Object).
                        await guild.ban(
                            member or discord.Object(id=uid), reason=p.get("reason") or None
                        )
                    elif member is None:
                        continue  # kick/timeout need the person still in the server
                    elif pending.kind == "kick":
                        await member.kick(reason=p.get("reason") or None)
                    else:
                        await member.timeout(
                            timedelta(minutes=p["minutes"]), reason=p.get("reason") or None
                        )
                except discord.DiscordException:
                    # Discord blocked it (missing permission, owner, 2FA…) -> report back, DON'T let the exception fly.
                    failed.append(member.display_name if member else str(uid))
                    continue
                done += 1
            # Past-tense verb per action (avoid naive "+ed" -> "Baned"/"Timeouted").
            _past = {"kick": "Kicked", "ban": "Banned", "timeout": "Timed out"}
            msg = f"{_past[pending.kind]} {done} people."
            if blocked:
                msg += (
                    f" Skipped (server owner / role higher-or-equal to bot): {', '.join(blocked)}."
                )
            if failed:
                msg += f" Discord rejected: {', '.join(failed)}."
            return msg

        if pending.kind == "untimeout":
            target_ids, err = _resolve_member_ids(guild, p.get("target_ids"), p.get("query"))
            if err:
                return err
            done = 0
            for uid in target_ids:
                member = guild.get_member(uid)
                if member is None:
                    continue
                await member.timeout(None, reason=p.get("reason") or None)  # None = remove timeout
                done += 1
            return f"Removed timeout for {done} people."

        if pending.kind == "unban":
            wanted_ids = set(p.get("target_ids") or [])
            query = (p.get("query") or "").strip().lower().lstrip("@")
            qnorm = query.replace("-", "").replace("_", "").replace(" ", "")
            bans = [e async for e in guild.bans(limit=1000)]

            def _hit(u) -> bool:
                if u.id in wanted_ids:
                    return True
                if not query:
                    return False
                if query == str(u.id):
                    return True
                # Combine username + global_name + str(user), loose match (drop -/_/space)
                names = " ".join(
                    x for x in (u.name, getattr(u, "global_name", None), str(u)) if x
                ).lower()
                if query in names:
                    return True
                names_norm = names.replace("-", "").replace("_", "").replace(" ", "")
                return bool(qnorm) and qnorm in names_norm

            matched = [e.user for e in bans if _hit(e.user)]
            if matched:
                for u in matched:
                    await guild.unban(u, reason=p.get("reason") or None)
                return "Unbanned: " + ", ".join(u.name or str(u.id) for u in matched)
            if not bans:
                return "The ban list is empty — nobody to unban."
            # No match -> LIST the ban list with IDs (deleted accounts have hard-to-type names, unban by ID).
            lines = "\n".join(f"- {e.user.name or '(no name)'} — ID {e.user.id}" for e in bans[:20])
            return (
                f"Nobody matched '{query}'. The ban list currently has:\n{lines}\n"
                "Retype the exact name or ID (e.g. 'unban 123456')."
            )

        if pending.kind == "toggle_plugin":
            repo_cls, fieldname = PLUGIN_TOGGLES[p["plugin"]]
            g = await GuildRepository(session).get_by_discord_id(guild.id)
            if g is None:
                return "Server isn't registered with the bot."
            await repo_cls(session).upsert(g.id, {fieldname: p["enabled"]})
            return f"{'Enabled' if p['enabled'] else 'Disabled'} plugin {p['plugin']}."
    except discord.Forbidden:
        return "The bot lacks permission to do this (check the bot's permissions + role rank)."
    except discord.HTTPException:
        log.warning("action execute HTTPException kind=%s", pending.kind)
        return "Discord rejected the operation, try again later."

    return f"Unsupported action: {pending.kind}"
