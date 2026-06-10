"""Claw Agent cog — on_message conversation + memory admin commands.

Responds when the bot is @mentioned (new conversation) or when a user replies to a
bot message (continues the conversation). Gating: enabled + agent_enabled +
(agent_channel_id None or matches the channel). Per-user cooldown to fight spam.
Requires intents.message_content (already enabled).
"""

import asyncio
import logging
import re
import time

import discord
from discord import app_commands
from discord.ext import commands

from app.db.session import session_scope
from app.discord_io.client import DiscordClient
from app.discord_io.errors import DiscordError
from app.repositories.agent_message import AgentMessageRepository
from app.repositories.ai_config import AIConfigRepository
from app.repositories.ai_usage import AIUsageRepository
from app.repositories.guild import GuildRepository
from app.repositories.memory_doc import MemoryDocRepository
from app.repositories.reminder import ReminderRepository
from app.repositories.subscription import SubscriptionRepository
from app.repositories.user_memory import UserMemoryRepository
from app.services.ai.actions.registry import ACTION_PERMS
from app.services.ai.actions.registry import execute as run_action
from app.services.ai.agent_service import AgentService
from app.services.ai.ai_gateway import AIGateway
from app.services.ai.provider import get_ai_provider

log = logging.getLogger(__name__)

AGENT_COOLDOWN = 5.0  # seconds between 2 messages from the same user
# --- Processing queue (many people mentioning AT THE SAME TIME) --------------------
# Previously, messages arriving while the bot was busy were DROPPED (⏳). Now they get
# queued for a worker pool that runs them sequentially -> we don't drop other people's
# valid messages, while still blocking spam.
AGENT_WORKERS = 3  # max agent runs IN PARALLEL (caps LLM-call storms -> protects DB pool + cost)
AGENT_QUEUE_MAX = 64  # queue capacity; over this = whole server overloaded -> drop (⏳) instead of growing forever
AGENT_PER_USER_MAX = (
    2  # 1 person can queue at most 2 runs (waiting + running) -> stops one person hogging the queue
)
CHANNEL_CONTEXT_LIMIT = 12  # number of recent channel messages fed to the bot to stay on-topic
_PERM_FLAGS = ("manage_guild", "manage_roles", "ban_members", "kick_members", "moderate_members")


async def collect_channel_context(channel, *, before, limit: int = CHANNEL_CONTEXT_LIMIT) -> str:
    """Read the MOST recent channel messages (before the one being processed) into a
    'Name: content' string in chronological order, so the bot stays on-topic with the
    ongoing conversation. History read errors (missing perms) -> return empty string,
    don't block the reply flow."""
    lines: list[str] = []
    try:
        async for m in channel.history(limit=limit, before=before):
            text = (m.clean_content or "").strip().replace("\n", " ")
            if not text:
                continue
            who = getattr(m.author, "display_name", str(m.author))
            lines.append(f"{who}: {text}"[:300])
    except (DiscordError, discord.DiscordException, AttributeError):
        return ""
    lines.reverse()  # history() yields new->old; reverse to old->new for readability
    return "\n".join(lines)


def _distinctive(name: str) -> bool:
    """Is the name DISTINCTIVE enough to auto-tag (to reduce accidental pings)?

    Discord usernames (e.g. 'thinh.nguyen2') almost always contain '.', '_' or a digit
    -> rarely collide with common words. Plain-letter names must be long (>=6) before we
    tag, so names like 'minh'/'Dat' (which collide with everyday Vietnamese words) DON'T
    get mistakenly turned into mentions.
    """
    return len(name) >= 6 or any(c.isdigit() or c in "._" for c in name)


def tag_known_members(text: str, guild, bot_id) -> str:
    """Turn member names (username/global_name) appearing in text into '<@id>' so the bot
    TAGS the right person (a real ping), even when memory only stored the PLAIN-TEXT name
    (without an id).

    Safe: only replaces DISTINCTIVE names (see _distinctive), on proper word boundaries,
    not already inside an existing '<@...>', and each person at most once. On error/broken
    regex -> return the original text, don't block sending.
    """
    if not text or guild is None:
        return text
    members = getattr(guild, "members", None) or []
    # (name, id): gather username, global_name AND display_name (nickname — e.g. 'ᴊᴀᴄᴋʏ ᴄʜᴜɴ').
    # Prefer LONGER names first to match the longest run ('thinh.nguyen2' before 'thinh').
    idents: list[tuple[str, int]] = []
    for m in members:
        if getattr(m, "id", None) == bot_id:
            continue
        seen: set[str] = set()
        for nm in (
            getattr(m, "name", None),
            getattr(m, "global_name", None),
            getattr(m, "display_name", None),
        ):
            if nm and nm not in seen:
                seen.add(nm)
                idents.append((nm, int(m.id)))
    idents.sort(key=lambda x: len(x[0]), reverse=True)
    for nm, uid in idents:
        if f"<@{uid}>" in text:  # already a valid ID mention -> skip
            continue
        esc = re.escape(nm)
        # (a) The model often FABRICATES '<@thinh.nguyen2>' / '<@!thinh.nguyen2>' (jamming a name
        # into mention syntax, but Discord needs a NUMERIC ID -> renders as plain text). Fix to a
        # real '<@id>'.
        text = re.sub(rf"<@!?{esc}>", f"<@{uid}>", text, count=1, flags=re.IGNORECASE)
        if f"<@{uid}>" in text:
            continue
        # (b) The model writes '@Name' (has @ but is NOT a real mention -> Discord shows junk with @).
        # @ = a clear INTENT to tag, so convert '@Name' -> '<@id>' even for non-'distinctive' names
        # (just need >=3 chars, skipping @everyone/@here). This is the '@ᴊᴀᴄᴋʏ ᴄʜᴜɴ' (nickname) case.
        if len(nm) >= 3 and nm.lower() not in ("everyone", "here"):
            new = re.sub(rf"(?<!\w)@{esc}(?!\w)", f"<@{uid}>", text, count=1, flags=re.IGNORECASE)
            if new != text:
                text = new
                continue
        # (c) PLAIN-TEXT name (no @) -> only convert if DISTINCTIVE (avoid mis-pinging common words).
        if _distinctive(nm):
            text = re.sub(
                rf"(?<![\w@<]){esc}(?![\w>])", f"<@{uid}>", text, count=1, flags=re.IGNORECASE
            )
    # FINAL PASS — clean up ANY remaining FABRICATED mention: '<@...>' / '<@!...>' whose inside is
    # NOT all DIGITS (Discord only renders a mention when it's a numeric id). E.g. the model invents
    # '<@rolt9>' (the bot name) or '<@unknown-name>' -> renders as junk. Strip the '<@ >' wrapper and
    # leave the plain name. Keep roles '<@&id>' (the '&' character).
    text = re.sub(r"<@!?([^0-9>&][^>]*)>", r"\1", text)
    return text


def perms_dict(guild_permissions) -> dict:
    """Extract action-relevant permission flags into a dict (to gate the stage + confirm)."""
    return {f: bool(getattr(guild_permissions, f, False)) for f in _PERM_FLAGS}


def confirm_perm_ok(kind: str, perms: dict) -> bool:
    """Does the person clicking ✅ have enough permission for this action (Administrator has every flag)?"""
    return bool(perms.get(ACTION_PERMS.get(kind, "")))


class ActionConfirmView(discord.ui.View):
    """✅/❌ buttons for DESTRUCTIVE actions (ban/kick/timeout/delete_role)."""

    def __init__(self, pending, *, on_resolve=None):
        super().__init__(timeout=120)
        self.pending = pending
        # Called when a button is clicked (✅/❌) -> lets the cog drop it from the
        # 'pending buttons' registry, so a later command doesn't accidentally overwrite a
        # message that was already handled.
        self._on_resolve = on_resolve

    def _resolve(self) -> None:
        if self._on_resolve is not None:
            try:
                self._on_resolve()
            except Exception:  # noqa: BLE001 — registry cleanup errors must not block the flow
                pass

    @discord.ui.button(label="✅ Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not confirm_perm_ok(self.pending.kind, perms_dict(interaction.user.guild_permissions)):
            await interaction.response.send_message(
                "You don't have enough permission for this action.", ephemeral=True
            )
            return
        # Wrap run_action: on error (DB/Discord/…) REPORT THE ERROR right on the button, DON'T leave
        # the interaction hanging silently (previously an exception here = clicking ✅ did nothing, and
        # the user thought it was broken).
        try:
            async with session_scope() as session:
                res = await run_action(self.pending, guild=interaction.guild, session=session)
            content = f"✅ {res}"
        except Exception:  # noqa: BLE001 — every error must surface to the clicker, never swallowed
            log.exception("agent confirm: run_action crashed (kind=%s)", self.pending.kind)
            content = "❌ Something broke running this action — try again later."
        try:
            await interaction.response.edit_message(content=content, view=None)
        except (DiscordError, discord.DiscordException):
            pass
        self._resolve()
        self.stop()

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="Cancelled.", view=None)
        self._resolve()
        self.stop()


def is_addressed(message, bot_user) -> bool:
    """True if the message is ADDRESSED TO the bot:
    - @mentions the actual bot user;
    - replies to a BOT MESSAGE (not a reply to someone else);
    - mentions the bot's ROLE (auto-generated role with the bot's name) — via role_mentions;
    - STARTS with the bot's name as text/render (e.g. '@rolt9 ...'/'rolt9 ...').
    """
    if any(getattr(u, "id", None) == bot_user.id for u in message.mentions):
        return True
    # Reply: ONLY counts when replying to a BOT MESSAGE. Previously it accepted EVERY reply -> the bot
    # jumped in even when 2 people were replying back and forth (nothing to do with the bot). That was
    # the bug.
    ref = getattr(message.reference, "resolved", None) if message.reference else None
    ref_author = getattr(ref, "author", None)
    if ref_author is not None and getattr(ref_author, "id", None) == bot_user.id:
        return True
    # Mention of the bot's own role (guild.me has that role).
    me = getattr(getattr(message, "guild", None), "me", None)
    role_mentions = getattr(message, "role_mentions", None) or []
    if me is not None and role_mentions:
        my_role_ids = {getattr(r, "id", None) for r in getattr(me, "roles", [])}
        if any(getattr(r, "id", None) in my_role_ids for r in role_mentions):
            return True
    # Bot name at the START of the message — must have a word boundary after the name (so 'rolt9000...'
    # doesn't wrongly match 'rolt9').
    name = (getattr(bot_user, "name", "") or "").lower()
    if name:
        for attr in ("clean_content", "content"):
            text = (getattr(message, attr, "") or "").lstrip().lower()
            for prefix in (f"@{name}", name):
                if text.startswith(prefix):
                    rest = text[len(prefix) :]
                    if rest == "" or not rest[0].isalnum():
                        return True
    return False


class CooldownTracker:
    """In-memory cooldown (rolt9 runs as 1 process).

    Keyed by (guild_id, user_id) -> each server tracks its own cooldown, so the same
    person messaging the bot in 2 different servers does NOT block cross-server.
    """

    def __init__(self, seconds: float):
        self._seconds = seconds
        self._last: dict[tuple[int, int], float] = {}

    def ready(self, guild_id: int, user_id: int, *, now: float) -> bool:
        last = self._last.get((guild_id, user_id))
        return last is None or (now - last) >= self._seconds

    def mark(self, guild_id: int, user_id: int, *, now: float) -> None:
        self._last[(guild_id, user_id)] = now


def _build_service(session) -> AgentService:
    gateway = AIGateway(
        guild_repo=GuildRepository(session),
        config_repo=AIConfigRepository(session),
        usage_repo=AIUsageRepository(session),
        provider=get_ai_provider(),
    )
    return AgentService(
        guild_repo=GuildRepository(session),
        config_repo=AIConfigRepository(session),
        agent_msg_repo=AgentMessageRepository(session),
        memory_repo=UserMemoryRepository(session),
        memory_doc_repo=MemoryDocRepository(session),
        reminder_repo=ReminderRepository(session),
        subscription_repo=SubscriptionRepository(session),
        gateway=gateway,
    )


class AgentCog(commands.Cog):
    def __init__(self, bot: commands.Bot, discord_io: DiscordClient):
        self.bot = bot
        self.discord_io = discord_io
        self.cooldown = CooldownTracker(AGENT_COOLDOWN)
        # Queue of bot-addressed messages + worker pool: many people mentioning AT THE SAME TIME
        # get QUEUED and run sequentially (AGENT_WORKERS in parallel) instead of being dropped or
        # spawning endless LLM threads.
        self._queue: asyncio.Queue[discord.Message] = asyncio.Queue(maxsize=AGENT_QUEUE_MAX)
        self._workers: list[asyncio.Task] = []
        # Number of runs each (guild,user) has waiting/running -> stops one person flooding the queue.
        self._pending: dict[tuple[int, int], int] = {}
        # ✅/❌ buttons waiting to be clicked, keyed by (channel, action kind, target) -> a new
        # destructive command of the SAME kind+person disables the old button (avoids clicking a
        # stale value, e.g. changing a timeout from 5m->10m).
        self._pending_confirms: dict[tuple, discord.Message] = {}

    def _ensure_workers(self) -> None:
        """Ensure the worker pool is running (idempotent).

        Called from cog_load on cog load, and as a safety net at the top of on_message — uses
        asyncio.create_task (running loop) so it works both at runtime and in tests.
        """
        if self._workers:
            return
        self._workers = [asyncio.create_task(self._worker(i)) for i in range(AGENT_WORKERS)]

    async def cog_load(self) -> None:
        """Start the worker pool when the cog is loaded (the event loop exists by now)."""
        self._ensure_workers()

    async def cog_unload(self) -> None:
        """Cancel the worker pool on cog unload/reload -> don't leave orphan background tasks."""
        for t in self._workers:
            t.cancel()
        self._workers = []

    async def _worker(self, n: int) -> None:
        """Loop: take 1 message off the queue -> process it -> repeat.

        Each worker handles 1 agent run at a time; total parallelism = AGENT_WORKERS.
        A failing message must NOT kill the worker (it has to keep serving others in the queue).
        """
        while True:
            message = await self._queue.get()
            key = (int(message.guild.id), message.author.id)
            try:
                await self._process(message)
            except Exception:  # noqa: BLE001 — swallow one message's error so the worker stays alive
                log.exception("agent worker %d: _process crashed", n)
            finally:
                # Return one pending slot to this person + mark one queue item done.
                remaining = self._pending.get(key, 1) - 1
                if remaining > 0:
                    self._pending[key] = remaining
                else:
                    self._pending.pop(key, None)
                self._queue.task_done()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        if self.bot.user is None or not is_addressed(message, self.bot.user):
            return

        self._ensure_workers()
        now = time.monotonic()
        key = (int(message.guild.id), message.author.id)
        # 3 overload gates, checked IN ORDER; failing any one reacts ⏳ + logs the reason:
        #   1) cooldown : the same person can trigger the bot only once / AGENT_COOLDOWN secs (anti-spam).
        #   2) per-user : one person can queue at most AGENT_PER_USER_MAX runs (anti queue-hogging).
        #   3) full     : queue is full (whole server overloaded) -> drop so it doesn't grow forever.
        # Pass all -> ENQUEUE; a worker will handle it sequentially (without dropping others' messages).
        if not self.cooldown.ready(*key, now=now):
            await self._throttle(message, "cooldown")
            return
        if self._pending.get(key, 0) >= AGENT_PER_USER_MAX:
            await self._throttle(message, "too-many-runs")
            return
        try:
            self._queue.put_nowait(message)
        except asyncio.QueueFull:
            await self._throttle(message, "queue-full")
            return
        # Enqueued successfully -> mark cooldown + bump this person's pending counter.
        self.cooldown.mark(*key, now=now)
        self._pending[key] = self._pending.get(key, 0) + 1

    async def _throttle(self, message: discord.Message, reason: str) -> None:
        """Signal throttling with a ⏳ reaction (lightweight, NO new message so the bot doesn't self-spam) + log the reason."""
        log.info(
            "agent throttle (%s) user=%s guild=%s", reason, message.author.id, message.guild.id
        )
        try:
            await message.add_reaction("⏳")
        except (DiscordError, discord.DiscordException):
            pass

    async def _process(self, message: discord.Message) -> None:
        """Process 1 bot-addressed message (after passing slowmode + the in-progress lock)."""
        user_text = message.clean_content
        ref_id = (
            int(message.reference.message_id)
            if message.reference and message.reference.message_id
            else None
        )
        g = message.guild
        server_snapshot = {
            "member_count": getattr(g, "member_count", 0) or 0,
            "roles": [r.name for r in getattr(g, "roles", []) if r.name != "@everyone"][:50],
            "channels": [c.name for c in getattr(g, "channels", [])][:50],
            # owner_id -> so the stage rejects ban/kick/timeout on the SERVER OWNER immediately (no confirm button).
            "owner_id": getattr(g, "owner_id", None),
        }
        bot_id = self.bot.user.id if self.bot.user else None
        target_user_ids = [u.id for u in message.mentions if u.id != bot_id]
        # 'Name = <@id>' for @mentioned people -> so the bot remembers them WITH an id and tags the right person later.
        mention_map = "; ".join(
            f"{getattr(u, 'display_name', None) or u.name} = <@{u.id}>"
            for u in message.mentions
            if u.id != bot_id
        )
        commander_perms = perms_dict(message.author.guild_permissions)
        channel_context = await collect_channel_context(message.channel, before=message)
        async with session_scope() as session:
            svc = _build_service(session)
            try:
                # "rolt9 is typing..." while calling the model (4-8s) -> feels less frozen.
                async with message.channel.typing():
                    result = await svc.respond(
                        guild_discord_id=int(message.guild.id),
                        channel_id=int(message.channel.id),
                        user_discord_id=int(message.author.id),
                        user_name=getattr(message.author, "display_name", str(message.author)),
                        message_text=user_text,
                        reference_message_id=ref_id,
                        server_snapshot=server_snapshot,
                        commander_perms=commander_perms,
                        role_names=[r.name for r in getattr(g, "roles", [])],
                        target_user_ids=target_user_ids,
                        commander_id=int(message.author.id),
                        channel_context=channel_context,
                        mention_map=mention_map,
                    )
            except ValueError as e:
                await self._safe_reply(message, f"❌ {e}")
                return
            except Exception:
                # Unexpected error (tool/model crash) -> STILL say something to the user, don't go
                # silent (previously it just logged and returned -> bot went quiet, looked like it ate
                # the command).
                log.exception("agent: respond crashed")
                await self._safe_reply(
                    message, "❌ Something broke handling this — give it another shot."
                )
                return
            if result is None:
                return

            conversation_id, text, pending = result
            # (cooldown was already marked at the top, don't re-mark here)

            if pending:
                # ACTION TURN: run the tool FIRST, then report based on the REAL RESULT — DON'T send
                # the model's words (the model often "claims it did it" before the tool runs).
                # Destructive actions -> ✅/❌ buttons (only run WHEN clicked). create_role runs first
                # so "create role X then assign X" works.
                outcomes: list[str] = []
                last_sent = None
                for p in sorted(pending, key=lambda a: 0 if a.kind == "create_role" else 1):
                    if p.destructive:
                        last_sent = await self._send_confirm(message, p) or last_sent
                        # Save a SYSTEM marker stating CLEARLY it was NOT done yet -> on the next turn the
                        # model (a) won't parrot '(awaiting admin confirmation)' as prose, (b) won't assume
                        # the action is already done.
                        outcomes.append(
                            f"[system: ✅/❌ button just sent, NOT executed] {p.description}"
                        )
                    else:
                        res = await run_action(
                            p, guild=message.guild, session=session, channel=message.channel
                        )
                        log.info("agent action executed: kind=%s -> %s", p.kind, res)
                        if p.kind != "create_poll":  # poll is its own output already
                            last_sent = await self._safe_reply(message, f"✅ {res}") or last_sent
                        outcomes.append(res)
                # Save the turn based on the REAL RESULT (not the model's bogus prose).
                await svc.remember(
                    guild_discord_id=int(message.guild.id),
                    conversation_id=conversation_id,
                    user_discord_id=int(message.author.id),
                    user_text=user_text,
                    assistant_text=" | ".join(outcomes) or "(handled)",
                    bot_message_id=int(last_sent.id) if last_sent else 0,
                    channel_id=int(message.channel.id),
                )
            else:
                # CHAT TURN (no action): send the model's words normally.
                # Convert member names in the sentence -> '<@id>' so the bot TAGS the right person (ping),
                # even when memory only stored the plain-text name (e.g. 'thinh.nguyen2' without an id when taught).
                text = tag_known_members(text, message.guild, bot_id)
                sent = await self._safe_reply(message, text)
                if sent is None:
                    return
                await svc.remember(
                    guild_discord_id=int(message.guild.id),
                    conversation_id=conversation_id,
                    user_discord_id=int(message.author.id),
                    user_text=user_text,
                    assistant_text=text,
                    bot_message_id=int(sent.id),
                    channel_id=int(message.channel.id),
                )

    @staticmethod
    def _confirm_key(channel_id: int, pending) -> tuple:
        """Identity key for a confirm button by (channel, action kind, target) — so a NEW destructive
        command of the same kind + same person disables the old button (e.g. changing a timeout from
        5m->10m for the same person)."""
        params = getattr(pending, "params", {}) or {}
        tids = params.get("target_ids") or []
        target = (
            tuple(sorted(str(x) for x in tids)) if tids else str(params.get("query", "")).lower()
        )
        return (int(channel_id), pending.kind, target)

    async def _send_confirm(self, message, pending):
        """Send ✅/❌ buttons for a destructive action. If an OLD unclicked button for the same
        (channel,kind,person) exists -> disable it first (avoid clicking a stale value). Return the
        sent message (or None on error)."""
        key = self._confirm_key(message.channel.id, pending)
        old = self._pending_confirms.pop(key, None)
        if old is not None:
            try:
                await old.edit(content="⚠️ Replaced by a newer command below.", view=None)
            except (DiscordError, discord.DiscordException):
                pass
        try:
            sent = await message.channel.send(
                f"🤖 Confirm action: **{pending.description}**?",
                view=ActionConfirmView(
                    pending, on_resolve=lambda: self._pending_confirms.pop(key, None)
                ),
            )
        except (DiscordError, discord.DiscordException):
            log.warning("agent: failed to send confirm in channel %s", message.channel.id)
            return None
        self._pending_confirms[key] = sent
        return sent

    async def _safe_reply(self, message, content: str):
        try:
            return await message.reply(content[:2000], mention_author=False)
        except (DiscordError, discord.DiscordException):
            log.warning("agent: failed to reply in channel %s", message.channel.id)
            return None

    @app_commands.command(
        name="claw-forget", description="Delete the memory the bot holds about you (this server)"
    )
    async def claw_forget(self, interaction: discord.Interaction) -> None:
        async with session_scope() as session:
            guild = await GuildRepository(session).get_by_discord_id(int(interaction.guild_id))
            if guild is not None:
                await UserMemoryRepository(session).clear(guild.id, int(interaction.user.id))
        await interaction.response.send_message("🧹 Wiped my memory about you.", ephemeral=True)

    @app_commands.command(
        name="claw-memory", description="See what the bot remembers about you (this server)"
    )
    async def claw_memory(self, interaction: discord.Interaction) -> None:
        facts = ""
        async with session_scope() as session:
            guild = await GuildRepository(session).get_by_discord_id(int(interaction.guild_id))
            if guild is not None:
                facts = await UserMemoryRepository(session).get_facts(
                    guild.id, int(interaction.user.id)
                )
        await interaction.response.send_message(
            facts or "I don't remember anything about you yet.", ephemeral=True
        )

    @app_commands.command(
        name="claw-lore", description="View the server's shared memory (nicknames, rules, …)"
    )
    async def claw_lore(self, interaction: discord.Interaction) -> None:
        """Show the server-wide memory_doc. Anyone can view (read-only)."""
        doc = ""
        async with session_scope() as session:
            guild = await GuildRepository(session).get_by_discord_id(int(interaction.guild_id))
            if guild is not None:
                doc = await MemoryDocRepository(session).get_doc(guild.id)
        await interaction.response.send_message(
            f"📒 **Server memory:**\n{doc}"
            if doc.strip()
            else "The server has no shared memory yet.",
            ephemeral=True,
        )

    @app_commands.command(
        name="claw-lore-clear",
        description="Wipe the server's entire shared memory (needs Manage Server)",
    )
    async def claw_lore_clear(self, interaction: discord.Interaction) -> None:
        """Wipe the memory_doc. Only someone with Manage Server can (this is shared data)."""
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                "You need the **Manage Server** permission to wipe the shared memory.",
                ephemeral=True,
            )
            return
        async with session_scope() as session:
            guild = await GuildRepository(session).get_by_discord_id(int(interaction.guild_id))
            if guild is not None:
                await MemoryDocRepository(session).clear(guild.id)
        await interaction.response.send_message(
            "🧹 Wiped the server's shared memory.", ephemeral=True
        )
