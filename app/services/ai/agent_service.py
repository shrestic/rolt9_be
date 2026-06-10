"""AgentService — the core of Claw Agent: builds context, calls the AI multi-turn, saves turns, extracts facts.

The cog (AgentCog) handles the Discord side (mention/reply, cooldown, sending messages); the service handles
logic + DB + calling the gateway. Every AI call goes through AIGateway (USD budget + token/cost).
"""

import re
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.repositories.agent_message import AgentMessageRepository
from app.repositories.ai_config import AIConfigRepository
from app.repositories.guild import GuildRepository
from app.repositories.memory_doc import MemoryDocRepository
from app.repositories.reminder import ReminderRepository
from app.repositories.subscription import SubscriptionRepository
from app.repositories.user_memory import UserMemoryRepository
from app.services.ai.ai_gateway import AIGateway
from app.services.ai.tools.registry import ToolContext
from app.services.ai.tools.runner import run_with_tools

DEFAULT_PERSONA = "You're a friendly assistant, keep replies short and natural, in English."

_VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")  # VN time so the model can work out reminder timestamps

TURN_LIMIT = 20
HISTORY_CHAR_CAP = 6000
FACTS_CHAR_CAP = 1500
MAX_FACTS = 15

# When a user sends another message WITHOUT replying: if they spoke in the same (channel, person) within
# this window, continue the old conversation for a natural feel; longer silence -> treat as a new one. A reply
# always takes priority over this mechanism (see `respond`).
CONVERSATION_WINDOW = timedelta(minutes=20)

# Nudge the model to PROACTIVELY use tools/actions instead of just replying with words — noticeably
# lifts the tool-call rate (even on weaker models). Only granted tools can be called.
_TOOL_NUDGE = (
    "You HAVE tools: web search, view server info, check the time, set a reminder / view / edit / cancel reminders, "
    "subscribe to a daily digest / edit / unsubscribe, create a poll & delete a poll, "
    "and (if granted) perform actions on the server — "
    "create/assign/remove/delete roles, kick/ban/unban members, timeout (mute) and untimeout (unmute/remove mute), "
    "enable/disable plugins. "
    "ONLY call a tool when the user ACTUALLY asks for it. Greetings / idle chit-chat / how-are-yous "
    "(e.g. 'yo', 'ey rolt9', 'hey you', 'rolt9 you there', 'sup', 'wassup') -> ANSWER STRAIGHT in words, "
    "ABSOLUTELY don't call any tool (no web_search, no current_time, no remember...). "
    "When the user ASKS for an action, CALL the right action tool STRAIGHT away — "
    "DON'T call server_info to 'check' first; the system validates the role/member itself when you call the tool "
    "and will report back if it's wrong, so just call the action tool already. "
    "The person mentioned (@) in the message is the target of the action. "
    "For unban, the banned person has already left the server so they CAN'T be @'d — pass their name/ID into the 'user' param. "
    "NO MATTER how sassy/savage your personality is, when asked for an action you MUST call the tool "
    "(want to tease? add it AFTER you've called the tool) — you can't just roast/joke and then forget to do it. "
    "For destructive actions (delete role, kick, ban, timeout): DON'T ask 'are you sure?' in words — "
    "just call the tool, the system will AUTOMATICALLY show ✅/❌ buttons for an admin to confirm. "
    "SUPER IMPORTANT — NO LYING: ABSOLUTELY do not say 'removed/muted/banned/kicked/assigned/"
    "let off/forgot/deleted/cancelled/stopped/done...' if you have NOT actually called the matching tool "
    "this turn. To do anything (including DELETE/FORGET a nickname, cancel a reminder, unsubscribe) you MUST call that tool "
    "FIRST, then report EXACTLY what the tool returned: if the tool says 'Forgot: X' then report you forgot X; if the tool says "
    "'no match found' then report NOT found — DON'T make up 'already deleted'. Soft phrasing like 'let them off', "
    "'cut them loose', 'set them free' = AN ACTION REQUEST -> call the tool (e.g. untimeout/unban), it's not just chatter. "
    "DON'T GUESS STATE: you DON'T know for sure who's banned/kicked/left/muted — "
    "even if earlier conversation mentioned it (an old command may have been cancelled/failed). When asked to kick/ban/"
    "mute/unmute someone, ABSOLUTELY don't refuse or make up things like 'they're already banned, why kick' — just CALL the tool, "
    "the system checks for real and reports back (e.g. 'can't kick the server owner', 'not found', 'higher role'). "
    "EVERY CRUD COMMAND — CREATE / READ / UPDATE / DELETE — for ANYTHING (reminders, digest subscriptions, "
    "memory/nicknames, polls, roles...): you MUST call the EXECUTING tool RIGHT NOW this turn. Applies to ALL 4, "
    "not just delete: CREATE ('set a reminder', 'subscribe', 'create a poll') -> call remind/subscribe/create_poll; "
    "READ ('any reminders', 'what am I following', 'what do you remember') -> call list_* / read 'SERVER MEMORY'; "
    "UPDATE ('change the time', 'change it to...') -> call edit_*; DELETE ('forget', 'cancel', 'delete') -> forget/cancel/unsubscribe. "
    "EVEN WHEN the conversation history (including your own) says 'done/set/deleted/gone/already there' "
    "— treat that as POSSIBLY WRONG/STALE, DON'T trust it, DON'T refuse with 'I already did that'/'already deleted that': just CALL THE TOOL again. "
    "The source of TRUTH is the tool result + the 'SERVER MEMORY' section (latest DB), NOT earlier chat. "
    "To view memory/nicknames -> read 'SERVER MEMORY' directly (any line present = STILL THERE, don't say it's deleted). "
    "To wipe all memory -> forget(all=true); to delete one -> forget(query). DON'T write 'deleted' via remember. "
    "If the tool result is EMPTY/0/not-found -> REPORT STRAIGHT ('no reminders', 'memory is empty', 'not "
    "found'), don't make up that you did it/it's there. "
    "DON'T PARROT SYSTEM LINES: phrases in the HISTORY like '(awaiting admin confirmation)...', 'Timeout 1 person for X min', "
    "'Banned/kicked/timed out...' are GENERATED BY THE SYSTEM, NOT a template for you to copy. ABSOLUTELY don't type "
    "'(awaiting admin confirmation)' yourself or describe an action as done — to timeout/ban/kick/mute someone just "
    "CALL THE TOOL, the system handles the ✅/❌ buttons + notification line. Changed your mind ('actually just 1 min') = CALL the tool again with the new number. "
    "TAGGING PEOPLE (DO THIS RIGHT so the mention always comes out as a blue pingable @): when referring to a person, "
    "JUST WRITE THEIR NAME/username/nickname (e.g. 'john.doe', 'big mike') — the SYSTEM AUTOMATICALLY turns it "
    "into a proper blue @mention. You DON'T need to and SHOULDN'T type out the number string '<@123456789>' (one wrong digit -> "
    "broken mention); only when an '<@id number>' is already provided in the 'People @'d in the message' section can you copy that exact "
    "string (that id is already correct). ABSOLUTELY DON'T make up '<@name>'/'<@username>' (e.g. <@john.doe>) —"
    "Discord can't tag it, it comes out as junk text; just write the plain name, the system handles it. "
    "DON'T ASSIGN IDENTITIES CARELESSLY: the person/subject being discussed (a profile on a link, a stranger, someone "
    "outside Discord) is BY DEFAULT DIFFERENT from the person in SERVER MEMORY — EVEN if the name matches or is similar (e.g. 'John "
    "Wanderer' on Facebook is NOT the <@id> of 'john.doe' just because they both have 'john'). ONLY "
    "tag '<@id>' when you're 100% CERTAIN it's the right person; if in doubt -> use the plain name, DON'T tag. "
    "And DON'T MAKE THINGS UP: if a link/web returns a LOGIN/blocked page (e.g. Facebook showing 'Log in') "
    "or has no real content -> just say 'can't view that link', ABSOLUTELY don't fabricate the info/"
    "identity/bio of the person in the link."
)

# Length rules — placed at the END of the system prompt (where the model sticks closest) and stated as taking
# priority over personality, otherwise the savage persona takes over and the bot rambles on, becomes nonsense.
_STYLE_GUIDE = (
    "REPLY RULES (more important than personality, you MUST follow these):\n"
    "- By default reply in 1 sentence, short and to the point — like texting, not writing an essay.\n"
    "- WHEN you JUST FINISHED something via a tool (set a reminder, created a poll, assigned/removed a role, kick/ban, enabled/disabled...): "
    "give ONLY a SHORT 1-sentence confirmation, e.g. 'Ok I'll ping you at 7pm', 'Poll's up, go vote'. Want to be sassy? "
    "Pack it TIGHTLY into that one sentence — DON'T add a follow-up clause that rambles, speculates, lectures, or drifts to something else.\n"
    "- DON'T open with a long wind-up, DON'T repeat yourself, DON'T 'go on' uselessly. Better short than nonsense.\n"
    "- Only write longer when someone GENUINELY asks for something that needs a detailed explanation (instructions, reasons)."
)

_EXTRACT_SYSTEM = (
    "You're a memory filter. Below are the facts already known about the user + one new exchange. "
    "Return a list of DURABLE, memorable facts about the user (name, interests, role, things they "
    "want you to remember), merged with the old ones, deduplicated, max 15 lines, one short fact per line. DON'T make things up. "
    "If there's nothing new worth remembering, return the old facts unchanged. Print only the list, one fact per "
    "line, no other text."
)


def build_system(
    persona: str,
    facts: str,
    user_name: str,
    memory_doc: str = "",
    channel_context: str = "",
    now_text: str = "",
    mention_map: str = "",
    user_id: int | None = None,
) -> str:
    """Assemble persona + server memory (memory_doc) + facts about the user + channel context
    into the system prompt. memory_doc is the server-wide lore (nicknames, rules, …) applied
    to EVERY turn; channel_context is a few recent messages in the channel so the bot stays on top of the conversation.
    now_text = current VN time so the model can work out timestamps when setting a reminder (the remind tool).
    mention_map = a 'name -> <@id>' map of people @'d in the message, so the model can TAG for real + remember with the id.
    user_id = the Discord id of the PERSON BEING TALKED TO -> so the model tags them correctly when they say 'I/me/my'
    (don't make up <@rolt9> = the bot's name to refer to them)."""
    base = persona or DEFAULT_PERSONA
    if user_id is not None:
        who = (
            f"\nYou're talking to <@{user_id}> (name: '{user_name}'). When they say "
            f"'I/me/my/myself', that IS <@{user_id}> — to remind/remember about them use "
            f"'<@{user_id}>', ABSOLUTELY DON'T use '<@rolt9>' (that's the BOT's name, not this person)."
        )
    else:
        who = f"\nYou're talking to '{user_name}'."
    parts = [base, _TOOL_NUDGE, who]
    if now_text:
        parts.append(f"\nRight now (VN time): {now_text}.")
    if mention_map.strip():
        # name -> <@id>: so when REMEMBERING or REFERRING TO a person, the model tags for real with <@id>
        # (e.g. remember '<@123> nickname big mike'), and later calls the right person, not plain text.
        parts.append(
            f"\nPeople @'d in the message (USE this exact <@id> string to tag/remember them): {mention_map.strip()}"
        )
    if memory_doc.strip():
        # Server-wide lore — always obey (e.g. "from now on call An X").
        # If this contains an <@number> form, when referring to that person USE <@number> to tag for real.
        parts.append(f"\nSERVER MEMORY (always apply):\n{memory_doc.strip()}")
    if facts.strip():
        parts.append(f"\nWhat you remember about this person:\n{facts.strip()}")
    if channel_context.strip():
        # Recent channel messages so it stays on top of the ongoing conversation.
        parts.append(f"\nA few recent messages in the channel:\n{channel_context.strip()}")
    # Length rules go LAST -> the model sticks to them closest, prevents rambling.
    parts.append(f"\n{_STYLE_GUIDE}")
    return "\n".join(parts)


# A quoted phrase (any quote style) — user-set nicknames are usually stored like this.
_NICK_QUOTE_RE = re.compile(r"[\"'“”‘’«»]([^\"'“”‘’«»\n]{2,40})[\"'“”‘’«»]")


def extract_nick_mentions(memory_doc: str) -> list[tuple[str, int]]:
    """Extract (nickname -> user id) pairs from SERVER MEMORY so we can tag for real later.

    Safe convention: only accept a LINE with EXACTLY 1 '<@id>' — then every quoted phrase on
    that line is treated as that person's nickname (e.g. '<@945> (Jacky) has the nickname "big mike"').
    Lines with multiple ids / no id -> skipped (to avoid mapping the wrong person).
    """
    out: list[tuple[str, int]] = []
    for line in (memory_doc or "").splitlines():
        ids = re.findall(r"<@!?(\d+)>", line)
        if len(set(ids)) != 1:
            continue
        uid = int(ids[0])
        for nick in _NICK_QUOTE_RE.findall(line):
            nick = nick.strip()
            if nick:
                out.append((nick, uid))
    return out


def apply_nick_mentions(text: str, memory_doc: str) -> str:
    """Turn user-set nicknames (e.g. 'big mike', '@big mike') in the reply into '<@id>' so the right person
    is ALWAYS tagged for real — even when the model only wrote the plain nickname. Prefer LONGER nicknames first."""
    if not text or not memory_doc:
        return text
    # DON'T skip by uid: one person can have MULTIPLE nicknames ('big mike' and 'lil mike') appearing
    # together -> we must tag ALL of them, don't skip just because we already tagged another nickname of theirs.
    # Prefer LONGER nicknames first to match the longest phrase; each nickname replaces EVERY occurrence.
    for nick, uid in sorted(
        extract_nick_mentions(memory_doc), key=lambda x: len(x[0]), reverse=True
    ):
        # '@big mike' or 'big mike' (plain text) at a word boundary -> '<@id>'.
        text = re.sub(rf"(?<!\w)@?{re.escape(nick)}(?!\w)", f"<@{uid}>", text, flags=re.IGNORECASE)
    return text


class AgentService:
    def __init__(
        self,
        *,
        guild_repo: GuildRepository,
        config_repo: AIConfigRepository,
        agent_msg_repo: AgentMessageRepository,
        memory_repo: UserMemoryRepository,
        memory_doc_repo: MemoryDocRepository,
        reminder_repo: ReminderRepository,
        subscription_repo: SubscriptionRepository,
        gateway: AIGateway,
    ):
        self.guild_repo = guild_repo
        self.config_repo = config_repo
        self.agent_msg_repo = agent_msg_repo
        self.memory_repo = memory_repo
        self.memory_doc_repo = memory_doc_repo
        self.reminder_repo = reminder_repo
        self.subscription_repo = subscription_repo
        self.gateway = gateway

    async def _guild_pk(self, guild_discord_id: int) -> uuid.UUID:
        guild = await self.guild_repo.get_by_discord_id(guild_discord_id)
        if guild is None:
            raise ValueError("Server isn't registered with the bot yet.")
        return guild.id

    async def respond(
        self,
        *,
        guild_discord_id: int,
        channel_id: int,
        user_discord_id: int,
        user_name: str,
        message_text: str,
        reference_message_id: int | None,
        server_snapshot: dict | None = None,
        commander_perms: dict | None = None,
        role_names: list[str] | None = None,
        target_user_ids: list[int] | None = None,
        commander_id: int | None = None,
        channel_context: str = "",
        mention_map: str = "",
    ) -> tuple[uuid.UUID, str, list] | None:
        """Gating + pick a conversation + call the AI. Returns (conversation_id, text, pending_actions),
        or None if the agent shouldn't reply. An AI config error raises ValueError so the cog reports ❌."""
        guild = await self.guild_repo.get_by_discord_id(guild_discord_id)
        if guild is None:
            return None
        cfg = await self.config_repo.get(guild.id)
        if cfg is None or not cfg.enabled or not cfg.agent_enabled:
            return None
        if cfg.agent_channel_id and channel_id != cfg.agent_channel_id:
            return None

        # Pick a conversation by 3 priority tiers:
        #   1) User REPLIED to a bot message -> continue that exact conversation (clearest signal).
        #   2) No reply, but they spoke in the same (channel, person) recently -> continue the
        #      most recent conversation (natural, doesn't force the user to reply).
        #   3) Otherwise -> a new conversation.
        conversation_id = None
        if reference_message_id is not None:
            conversation_id = await self.agent_msg_repo.conversation_of(reference_message_id)
        if conversation_id is None:
            conversation_id = await self.agent_msg_repo.latest_conversation(
                guild.id,
                channel_id=channel_id,
                user_discord_id=user_discord_id,
                within=CONVERSATION_WINDOW,
                now=datetime.now(UTC),
            )
        if conversation_id is None:
            conversation_id = uuid.uuid4()

        facts = await self.memory_repo.get_facts(guild.id, user_discord_id)
        memory_doc = await self.memory_doc_repo.get_doc(guild.id)
        history = await self.agent_msg_repo.recent_turns(
            conversation_id, limit=TURN_LIMIT, char_cap=HISTORY_CHAR_CAP
        )
        # Current VN time so the model can work out the timestamp when setting a reminder ("tomorrow 5:30" -> absolute).
        now_text = datetime.now(_VN_TZ).strftime("%Y-%m-%d %H:%M (%A)")
        system = build_system(
            cfg.persona,
            facts,
            user_name,
            memory_doc,
            channel_context,
            now_text,
            mention_map,
            user_id=user_discord_id,
        )

        perms = commander_perms or {}
        can_act = any(perms.values())
        include_actions = bool(cfg.actions_enabled) and can_act
        ctx = ToolContext(
            guild_snapshot=server_snapshot,
            can_act=can_act,
            role_names=role_names or [],
            target_user_ids=target_user_ids or [],
            commander_id=commander_id,
            commander_perms=perms,
            guild_discord_id=guild_discord_id,
            # The `remember` tool is ALWAYS available — writes to server memory via this repo.
            memory_repo_doc=self.memory_doc_repo,
            guild_pk=guild.id,
            # The `remind` tool — writes reminders; channel_id = the channel to ping in when the time comes.
            reminder_repo=self.reminder_repo,
            channel_id=channel_id,
            # The `subscribe`/`unsubscribe`/`list_subscriptions` tools — daily digest subscriptions.
            subscription_repo=self.subscription_repo,
        )

        # Always go through the tool-loop: the `remember` tool is always available, so there's no more "plain chat" branch.
        text = await run_with_tools(
            gateway=self.gateway,
            guild_discord_id=guild_discord_id,
            system=system,
            history=history,
            user_text=message_text,
            ctx=ctx,
            has_search=cfg.tools_enabled and bool(settings.TAVILY_API_KEY),
            include_actions=include_actions,
        )
        # User-set nicknames ('big mike'…) in the reply -> '<@id>' so the right person is ALWAYS tagged for real.
        text = apply_nick_mentions(text, memory_doc)
        return conversation_id, text, ctx.pending

    async def remember(
        self,
        *,
        guild_discord_id: int,
        conversation_id: uuid.UUID,
        user_discord_id: int,
        user_text: str,
        assistant_text: str,
        bot_message_id: int,
        channel_id: int | None = None,
    ) -> None:
        """After the reply has been sent: save both turns + asynchronously extract facts. A fact-extraction error doesn't block."""
        guild = await self.guild_repo.get_by_discord_id(guild_discord_id)
        if guild is None:
            return
        old_facts = await self.memory_repo.get_facts(guild.id, user_discord_id)
        await self.persist(
            guild.id,
            conversation_id,
            user_text,
            assistant_text,
            bot_message_id,
            channel_id=channel_id,
            user_discord_id=user_discord_id,
        )
        await self.extract_memory(
            guild_discord_id, user_discord_id, user_text, assistant_text, old_facts
        )

    async def persist(
        self,
        guild_id: uuid.UUID,
        conversation_id: uuid.UUID,
        user_text: str,
        assistant_text: str,
        bot_message_id: int,
        channel_id: int | None = None,
        user_discord_id: int | None = None,
    ) -> None:
        # Attach (channel, person) to BOTH turns -> later `latest_conversation` can find this
        # conversation when the user sends another message without replying.
        await self.agent_msg_repo.add_turn(
            guild_id,
            conversation_id,
            "user",
            user_text,
            channel_id=channel_id,
            user_discord_id=user_discord_id,
        )
        await self.agent_msg_repo.add_turn(
            guild_id,
            conversation_id,
            "assistant",
            assistant_text,
            discord_message_id=bot_message_id,
            channel_id=channel_id,
            user_discord_id=user_discord_id,
        )

    async def extract_memory(
        self,
        guild_discord_id: int,
        user_discord_id: int,
        user_text: str,
        assistant_text: str,
        old_facts: str,
    ) -> None:
        """Extract new facts (via the gateway) then upsert. On error/empty -> skip (don't raise)."""
        gid = await self._guild_pk(guild_discord_id)
        prompt = f"OLD FACTS:\n{old_facts}\n\n---\nUSER: {user_text}\nBOT: {assistant_text}"
        try:
            out = await self.gateway.complete(
                guild_discord_id=guild_discord_id, system=_EXTRACT_SYSTEM, prompt=prompt
            )
        except Exception:  # noqa: BLE001 — fact extraction is secondary, must not break the flow
            return
        lines = [ln.strip() for ln in out.splitlines() if ln.strip()][:MAX_FACTS]
        facts = "\n".join(lines)[:FACTS_CHAR_CAP]
        if facts:
            await self.memory_repo.upsert_facts(gid, user_discord_id, facts)
