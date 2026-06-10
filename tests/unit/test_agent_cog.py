import contextlib
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.bot.cogs.agent as agent_mod
from app.bot.cogs.agent import AGENT_COOLDOWN, AgentCog, CooldownTracker, is_addressed


class _User:
    def __init__(self, id, bot=False, name="rolt9", perms=None):
        self.id = id
        self.bot = bot
        self.name = name
        self.display_name = f"u{id}"
        flags = {
            "manage_guild": False,
            "manage_roles": False,
            "ban_members": False,
            "kick_members": False,
            "moderate_members": False,
        }
        flags.update(perms or {})
        self.guild_permissions = SimpleNamespace(**flags)


class _Ref:
    def __init__(self, mid, resolved=None):
        self.message_id = mid
        self.resolved = resolved  # the replied-to message (Message) if in cache


class _Typing:
    """Empty fake async context manager for channel.typing()."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Msg:
    def __init__(
        self,
        *,
        author=None,
        mentions=None,
        reference=None,
        guild=True,
        content="hello",
        clean_content="hello",
        role_mentions=None,
        me_role_ids=(),
    ):
        self.author = author or _User(2)
        self.mentions = mentions or []
        self.reference = reference
        self.content = content
        self.role_mentions = role_mentions or []
        self.guild = (
            SimpleNamespace(
                id=100,
                member_count=5,
                roles=[SimpleNamespace(name="@everyone"), SimpleNamespace(name="Mod")],
                channels=[SimpleNamespace(name="general")],
                me=SimpleNamespace(roles=[SimpleNamespace(id=rid) for rid in me_role_ids]),
            )
            if guild
            else None
        )
        self.channel = SimpleNamespace(id=10, send=AsyncMock(), typing=lambda: _Typing())
        self.clean_content = clean_content
        self.reply = AsyncMock(return_value=SimpleNamespace(id=555))
        self.add_reaction = AsyncMock()  # to test the ⏳ reaction when throttled


# ---------- pure helpers ----------


def test_is_addressed_by_mention():
    bot = _User(1)
    assert is_addressed(_Msg(mentions=[_User(1)]), bot) is True
    assert is_addressed(_Msg(mentions=[_User(2)]), bot) is False


def test_is_addressed_by_reply_to_bot_only():
    bot = _User(1)
    # reply to THE BOT'S message -> True
    ref_bot = _Ref(99, resolved=SimpleNamespace(author=_User(1)))
    assert is_addressed(_Msg(reference=ref_bot), bot) is True
    # reply to SOMEONE ELSE's message -> False (this was the old bug: accepting every reply)
    ref_other = _Ref(99, resolved=SimpleNamespace(author=_User(2)))
    assert is_addressed(_Msg(reference=ref_other), bot) is False
    # reply but can't resolve -> don't auto-accept (avoids replying by mistake)
    assert is_addressed(_Msg(reference=_Ref(99)), bot) is False
    assert is_addressed(_Msg(content="hi everyone"), bot) is False


def test_is_addressed_name_prefix_word_boundary():
    bot = _User(1, name="rolt9")
    assert is_addressed(_Msg(content="rolt9 hey"), bot) is True
    assert is_addressed(_Msg(content="rolt9000 what is"), bot) is False  # false match -> blocked


def test_is_addressed_by_name_text():
    bot = _User(1, name="rolt9")
    # typing "@rolt9 ..." as text (mention didn't form) is still accepted
    assert is_addressed(_Msg(content="@rolt9 what time is it?"), bot) is True
    assert is_addressed(_Msg(content="rolt9 hey help me out"), bot) is True
    assert is_addressed(_Msg(content="just chatting normally"), bot) is False


def test_is_addressed_by_clean_content_role_render():
    bot = _User(1, name="rolt9")
    # Mention a ROLE -> content has "<@&..>" but clean_content renders as "@rolt9"
    msg = _Msg(content="<@&999> what time", clean_content="@rolt9 what time")
    assert is_addressed(msg, bot) is True


def test_is_addressed_by_bot_role_mention():
    bot = _User(1, name="rolt9")
    role = SimpleNamespace(id=999)
    msg = _Msg(
        content="<@&999> hi", clean_content="@SomeRole hi", role_mentions=[role], me_role_ids=(999,)
    )
    assert is_addressed(msg, bot) is True


class _Member:
    """Fake member for guild.members in the tag_known_members tests."""

    def __init__(self, id, name=None, global_name=None, display_name=None):
        self.id = id
        self.name = name
        self.global_name = global_name
        self.display_name = display_name


def _guild_with(members):
    return SimpleNamespace(members=members)


def test_tag_known_members_username_to_mention():
    from app.bot.cogs.agent import tag_known_members

    g = _guild_with([_Member(42, name="thinh.nguyen2", global_name="Dat")])
    # a plain username in the sentence -> turn it into <@id> to ping
    out = tag_known_members("Dat = that thinh.nguyen2 guy", g, bot_id=1)
    assert "<@42>" in out
    assert "thinh.nguyen2" not in out  # the username was replaced


def test_tag_known_members_converts_at_display_name():
    from app.bot.cogs.agent import tag_known_members

    # Model writes '@ᴊᴀᴄᴋʏ ᴄʜᴜɴ' (an @ + fancy display name, NOT a real mention) -> '<@77>'.
    g = _guild_with([_Member(77, name="jackychun", display_name="ᴊᴀᴄᴋʏ ᴄʜᴜɴ")])
    out = tag_known_members("Report the gold price for @ᴊᴀᴄᴋʏ ᴄʜᴜɴ", g, bot_id=1)
    assert "<@77>" in out
    assert "@ᴊᴀᴄᴋʏ ᴄʜᴜɴ" not in out  # the fake @ became a real mention


def test_tag_known_members_at_form_skips_everyone():
    from app.bot.cogs.agent import tag_known_members

    # '@everyone' is NOT turned into a single-person mention (leave system tags alone).
    g = _guild_with([_Member(5, name="everyone")])
    out = tag_known_members("hi @everyone", g, bot_id=1)
    assert "<@5>" not in out
    assert "@everyone" in out


def test_tag_known_members_fixes_fabricated_mention():
    from app.bot.cogs.agent import tag_known_members

    g = _guild_with([_Member(42, name="thinh.nguyen2", global_name="Dat")])
    # Model FABRICATES '<@thinh.nguyen2>' (Discord won't render it since it needs a numeric ID) -> must fix to '<@42>'.
    out = tag_known_members("Dat = that <@thinh.nguyen2> real name Dat", g, bot_id=1)
    assert "<@42>" in out
    assert "<@thinh.nguyen2>" not in out
    assert out.count("<@42>") == 1  # not duplicated


def test_tag_known_members_fixes_fabricated_mention_bang_form():
    from app.bot.cogs.agent import tag_known_members

    g = _guild_with([_Member(42, name="thinh.nguyen2")])
    out = tag_known_members("hey <@!thinh.nguyen2> there", g, bot_id=1)
    assert out == "hey <@42> there"


def test_tag_known_members_skips_short_common_names():
    from app.bot.cogs.agent import tag_known_members

    # global_name 'Dat' (3 chars, plain letters) isn't distinctive enough -> don't tag (avoids mis-pinging).
    g = _guild_with([_Member(7, name="abc", global_name="Dat")])
    out = tag_known_members("Dat is having a good day today", g, bot_id=1)
    assert out == "Dat is having a good day today"  # unchanged


def test_tag_known_members_idempotent_and_no_double_tag():
    from app.bot.cogs.agent import tag_known_members

    g = _guild_with([_Member(42, name="thinh.nguyen2")])
    # already has <@42> -> don't insert another
    assert tag_known_members("hi <@42> there", g, bot_id=1) == "hi <@42> there"
    # don't touch an existing mention of someone else / a username inside <@...>
    out = tag_known_members("ping thinh.nguyen2", g, bot_id=1)
    assert out.count("<@42>") == 1


def test_tag_known_members_skips_bot_itself():
    from app.bot.cogs.agent import tag_known_members

    g = _guild_with([_Member(1, name="rolt9.bot")])
    out = tag_known_members("call rolt9.bot over", g, bot_id=1)
    assert "<@1>" not in out  # the bot itself -> don't tag


def test_tag_known_members_strips_fabricated_bot_mention():
    from app.bot.cogs.agent import tag_known_members

    # Model fabricates '<@rolt9>' (a mention of the bot itself, not a numeric id) -> Discord shows junk text.
    # Must drop the '<@ >' pair, leaving 'rolt9' (don't tag the bot itself).
    g = _guild_with([_Member(1, name="rolt9")])
    out = tag_known_members("Hello hello, <@rolt9>! What are you calling about?", g, bot_id=1)
    assert "<@rolt9>" not in out
    assert "rolt9" in out  # the plain name remains


def test_tag_known_members_strips_any_unknown_fabricated_mention():
    from app.bot.cogs.agent import tag_known_members

    # A name not in guild members that the model still fabricates as '<@someone>' -> clean back to plain text.
    g = _guild_with([])
    out = tag_known_members("ask <@someone> about it", g, bot_id=1)
    assert out == "ask someone about it"


def test_tag_known_members_keeps_valid_id_and_role_mentions():
    from app.bot.cogs.agent import tag_known_members

    g = _guild_with([_Member(42, name="thinh.nguyen2")])
    # '<@123>' (numeric id) and '<@&999>' (role) are both VALID -> keep them, don't clean by mistake.
    out = tag_known_members("hi <@123> and role <@&999>", g, bot_id=1)
    assert "<@123>" in out and "<@&999>" in out


def test_cooldown_tracker():
    t = CooldownTracker(AGENT_COOLDOWN)
    assert t.ready(7, 42, now=100.0) is True
    t.mark(7, 42, now=100.0)
    assert t.ready(7, 42, now=100.0 + AGENT_COOLDOWN - 1) is False
    assert t.ready(7, 42, now=100.0 + AGENT_COOLDOWN + 1) is True


def test_cooldown_tracker_scoped_by_guild():
    # Same user but different guild -> independent cooldown, no cross-server false blocking.
    t = CooldownTracker(AGENT_COOLDOWN)
    t.mark(7, 42, now=100.0)  # user 42 in guild 7
    assert t.ready(7, 42, now=100.0) is False  # same (guild, user) -> on cooldown
    assert t.ready(8, 42, now=100.0) is True  # same user, different guild -> NOT blocked


# ---------- on_message glue (patched session_scope + stub service) ----------


def _patch(monkeypatch, stub):
    @contextlib.asynccontextmanager
    async def fake_scope():
        yield MagicMock()

    monkeypatch.setattr(agent_mod, "session_scope", fake_scope)
    monkeypatch.setattr(agent_mod, "_build_service", lambda session: stub)


def _cog():
    bot = MagicMock()
    bot.user = _User(1)
    return AgentCog(bot, MagicMock())


async def _drain(cog):
    """Wait for the pool workers to finish the whole queue (on_message now only ENQUEUES,
    workers process asynchronously) — call before asserting respond/reply results."""
    await cog._queue.join()


@pytest.mark.asyncio
async def test_on_message_replies_and_remembers(monkeypatch):
    cid = uuid.uuid4()
    stub = MagicMock()
    stub.respond = AsyncMock(return_value=(cid, "reply", []))
    stub.remember = AsyncMock()
    _patch(monkeypatch, stub)
    cog = _cog()
    msg = _Msg(author=_User(2), mentions=[_User(1)])
    await cog.on_message(msg)
    await _drain(cog)
    msg.reply.assert_awaited_once()
    stub.respond.assert_awaited_once()
    stub.remember.assert_awaited_once()
    # bot_message_id comes from the sent message (555)
    assert stub.remember.call_args.kwargs["bot_message_id"] == 555
    # the cog gathers a server snapshot (member_count + roles minus @everyone) and passes it to respond
    snap = stub.respond.call_args.kwargs["server_snapshot"]
    assert snap["member_count"] == 5
    assert snap["roles"] == ["Mod"]


@pytest.mark.asyncio
async def test_on_message_ignores_not_addressed(monkeypatch):
    stub = MagicMock()
    stub.respond = AsyncMock()
    _patch(monkeypatch, stub)
    cog = _cog()
    await cog.on_message(_Msg(author=_User(2)))  # no mention, no reply
    stub.respond.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_message_ignores_bot_author(monkeypatch):
    stub = MagicMock()
    stub.respond = AsyncMock()
    _patch(monkeypatch, stub)
    cog = _cog()
    await cog.on_message(_Msg(author=_User(2, bot=True), mentions=[_User(1)]))
    stub.respond.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_message_none_result_no_reply(monkeypatch):
    stub = MagicMock()
    stub.respond = AsyncMock(return_value=None)  # agent off / wrong channel
    stub.remember = AsyncMock()
    _patch(monkeypatch, stub)
    cog = _cog()
    msg = _Msg(author=_User(2), mentions=[_User(1)])
    await cog.on_message(msg)
    await _drain(cog)
    msg.reply.assert_not_awaited()
    stub.remember.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_message_value_error_replies_error(monkeypatch):
    stub = MagicMock()
    stub.respond = AsyncMock(side_effect=ValueError("out of budget"))
    _patch(monkeypatch, stub)
    cog = _cog()
    msg = _Msg(author=_User(2), mentions=[_User(1)])
    await cog.on_message(msg)
    await _drain(cog)
    msg.reply.assert_awaited_once()
    assert "❌" in msg.reply.call_args.args[0]


@pytest.mark.asyncio
async def test_on_message_unexpected_error_still_replies_not_silent(monkeypatch):
    # Unexpected error (tool/model crash) -> STILL reply with a line, DON'T go silent (previously just logged and returned).
    stub = MagicMock()
    stub.respond = AsyncMock(side_effect=RuntimeError("tool blew up"))
    _patch(monkeypatch, stub)
    cog = _cog()
    msg = _Msg(author=_User(2), mentions=[_User(1)])
    await cog.on_message(msg)
    await _drain(cog)
    msg.reply.assert_awaited_once()
    assert "❌" in msg.reply.call_args.args[0]


@pytest.mark.asyncio
async def test_on_message_marks_cooldown_before_processing(monkeypatch):
    # Mark cooldown IMMEDIATELY (before respond): even if respond returns None / is slow, the 2nd message is still blocked.
    stub = MagicMock()
    stub.respond = AsyncMock(return_value=None)  # e.g. agent off / wrong channel
    stub.remember = AsyncMock()
    _patch(monkeypatch, stub)
    cog = _cog()
    u = _User(2)
    await cog.on_message(_Msg(author=u, mentions=[_User(1)]))
    await cog.on_message(_Msg(author=u, mentions=[_User(1)]))  # right after -> cooldown blocks
    await _drain(cog)
    assert stub.respond.await_count == 1  # 2nd blocked even though the 1st didn't reply


@pytest.mark.asyncio
async def test_on_message_per_user_cap_drops_overflow(monkeypatch):
    # One person can have at most AGENT_PER_USER_MAX turns queued (pending + running). The 3rd
    # is dropped (⏳) IMMEDIATELY, not stuffed into the queue. Disable cooldown to isolate the per-user gate.
    import asyncio

    gate = asyncio.Event()
    cid = uuid.uuid4()

    async def slow_respond(**kw):
        await gate.wait()  # keep the first turns "running" to occupy the pending slots
        return (cid, "ok", [])

    stub = MagicMock()
    stub.respond = AsyncMock(side_effect=slow_respond)
    stub.remember = AsyncMock()
    _patch(monkeypatch, stub)
    cog = _cog()
    cog.cooldown = CooldownTracker(0.0)  # disable cooldown -> only the per-user gate remains
    u = _User(2)
    await cog.on_message(_Msg(author=u, mentions=[_User(1)]))  # turn 1 -> pending=1
    await cog.on_message(_Msg(author=u, mentions=[_User(1)]))  # turn 2 -> pending=2 (slots full)
    msg3 = _Msg(author=u, mentions=[_User(1)])
    await cog.on_message(msg3)  # turn 3 -> pending already 2 -> dropped
    gate.set()
    await _drain(cog)
    assert stub.respond.await_count == 2  # only the first 2 turns processed
    msg3.add_reaction.assert_awaited_once_with("⏳")  # turn 3 throttled


@pytest.mark.asyncio
async def test_on_message_cooldown_blocks_second(monkeypatch):
    cid = uuid.uuid4()
    stub = MagicMock()
    stub.respond = AsyncMock(return_value=(cid, "ok", []))
    stub.remember = AsyncMock()
    _patch(monkeypatch, stub)
    cog = _cog()
    u = _User(2)
    await cog.on_message(_Msg(author=u, mentions=[_User(1)]))
    msg2 = _Msg(author=u, mentions=[_User(1)])  # immediately -> cooldown blocks
    await cog.on_message(msg2)
    await _drain(cog)
    assert stub.respond.await_count == 1
    msg2.add_reaction.assert_awaited_once_with("⏳")  # signal the throttle with a ⏳ reaction


@pytest.mark.asyncio
async def test_on_message_many_distinct_users_all_processed_no_throttle(monkeypatch):
    # WORRYING SCENARIO: many DIFFERENT people mention the bot within a short window.
    # Throttling is PER-USER (cooldown + per-user cap keyed by (guild,user)) -> different people
    # DON'T block each other; all get QUEUED and processed, nobody hits ⏳.
    cid = uuid.uuid4()
    stub = MagicMock()
    stub.respond = AsyncMock(return_value=(cid, "ok", []))
    stub.remember = AsyncMock()
    _patch(monkeypatch, stub)
    cog = _cog()
    # 10 different people (id 100..109), one command each — more than 3 workers to force queuing.
    msgs = [_Msg(author=_User(100 + i), mentions=[_User(1)]) for i in range(10)]
    for m in msgs:
        await cog.on_message(m)
    await _drain(cog)
    assert stub.respond.await_count == 10  # all 10 processed (queued, no drops)
    for m in msgs:
        m.add_reaction.assert_not_awaited()  # NOBODY throttled with ⏳


@pytest.mark.asyncio
async def test_on_message_concurrent_bans_all_call_tool(monkeypatch):
    # Many different people say "ban" within a short window -> the WHOLE GROUP can call the tool
    # (each turn stages 1 destructive action -> sends a confirm button). Nobody is dropped by throttling.
    cid = uuid.uuid4()
    danger = PendingAction("ban", True, "Ban 1 person", {"target_ids": [9], "reason": ""})
    stub = MagicMock()
    stub.respond = AsyncMock(return_value=(cid, "ok", [danger]))
    stub.remember = AsyncMock()
    _patch(monkeypatch, stub)
    run_mock = AsyncMock()
    monkeypatch.setattr(agent_mod, "run_action", run_mock)
    cog = _cog()
    msgs = [_Msg(author=_User(200 + i), mentions=[_User(1)]) for i in range(6)]
    for m in msgs:
        await cog.on_message(m)
    await _drain(cog)
    assert stub.respond.await_count == 6  # all 6 agent turns run (call the ban tool)
    assert sum(m.channel.send.await_count for m in msgs) == 6  # one confirm button per person
    run_mock.assert_not_awaited()  # destructive -> wait for ✅, not executed yet
    for m in msgs:
        m.add_reaction.assert_not_awaited()  # nobody hits ⏳


@pytest.mark.asyncio
async def test_on_message_same_user_spam_bans_throttled(monkeypatch):
    # CONVERSELY: the SAME person spamming "ban" repeatedly -> cooldown lets only 1 turn through,
    # the rest get ⏳ (this is the DESIRED anti-spam behavior, not a bug).
    cid = uuid.uuid4()
    danger = PendingAction("ban", True, "Ban 1 person", {"target_ids": [9], "reason": ""})
    stub = MagicMock()
    stub.respond = AsyncMock(return_value=(cid, "ok", [danger]))
    stub.remember = AsyncMock()
    _patch(monkeypatch, stub)
    monkeypatch.setattr(agent_mod, "run_action", AsyncMock())
    cog = _cog()
    u = _User(2)
    spam = [_Msg(author=u, mentions=[_User(1)]) for _ in range(5)]
    for m in spam:
        await cog.on_message(m)  # fired back-to-back within the same cooldown window
    await _drain(cog)
    assert stub.respond.await_count == 1  # only their first turn is processed
    throttled = sum(m.add_reaction.await_count for m in spam[1:])
    assert throttled == 4  # the 4 later spam turns all get ⏳


@pytest.mark.asyncio
async def test_on_message_overload_sheds_load_no_loss_no_crash(monkeypatch):
    # WORST CASE: the whole server spams non-stop, more than the queue can hold.
    # Guarantee 3 properties: (1) NO crash/hang; (2) NO lost messages — each is EITHER processed
    # OR ⏳; (3) messages that make it into the queue ARE still processed (respond/reply run fully).
    import asyncio

    from app.bot.cogs.agent import AGENT_QUEUE_MAX, AGENT_WORKERS

    gate = asyncio.Event()
    cid = uuid.uuid4()

    async def slow(**kw):
        await gate.wait()  # keep workers busy so the queue piles up -> force hitting the ceiling
        return (cid, "reply", [])

    stub = MagicMock()
    stub.respond = AsyncMock(side_effect=slow)
    stub.remember = AsyncMock()
    _patch(monkeypatch, stub)
    cog = _cog()
    cog.cooldown = CooldownTracker(0.0)  # disable cooldown -> isolate the "queue full" gate
    # Each person is DIFFERENT (bypass cooldown + per-user) to pack the global queue as full as possible.
    total = AGENT_WORKERS + AGENT_QUEUE_MAX + 8  # 8 extra people -> definitely overflows
    msgs = [_Msg(author=_User(1000 + i), mentions=[_User(1)]) for i in range(total)]
    for m in msgs:
        await cog.on_message(m)  # (1) fired back-to-back non-stop — must not raise/hang
    gate.set()
    await _drain(cog)

    dropped = sum(1 for m in msgs if m.add_reaction.await_count > 0)  # hit ⏳
    processed = sum(1 for m in msgs if m.reply.await_count > 0)  # replied (respond finished)
    assert dropped >= 1  # (1+3) sheds load when overloaded -> the queue does NOT grow unbounded
    assert dropped + processed == total  # (2) NO lost messages: each is either processed or ⏳
    assert processed >= AGENT_QUEUE_MAX  # (3) most are still processed fully (respond called)


# ---------- actions (perms + pending handling) ----------

from app.bot.cogs.agent import confirm_perm_ok, perms_dict  # noqa: E402
from app.services.ai.actions.registry import PendingAction  # noqa: E402


def test_perms_dict_and_confirm_perm_ok():
    gp = SimpleNamespace(
        manage_guild=True,
        manage_roles=False,
        ban_members=True,
        kick_members=False,
        moderate_members=False,
    )
    d = perms_dict(gp)
    assert d["manage_guild"] is True and d["ban_members"] is True and d["manage_roles"] is False
    assert confirm_perm_ok("ban", d) is True  # needs ban_members -> has it
    assert confirm_perm_ok("create_role", d) is False  # needs manage_roles -> doesn't have it


@pytest.mark.asyncio
async def test_on_message_executes_safe_action(monkeypatch):
    cid = uuid.uuid4()
    safe = PendingAction(
        "toggle_plugin", False, "Enable welcome", {"plugin": "welcome", "enabled": True}
    )
    stub = MagicMock()
    stub.respond = AsyncMock(return_value=(cid, "ok", [safe]))
    stub.remember = AsyncMock()
    _patch(monkeypatch, stub)
    run_mock = AsyncMock(return_value="Enabled welcome.")
    monkeypatch.setattr(agent_mod, "run_action", run_mock)
    cog = _cog()
    msg = _Msg(author=_User(2), mentions=[_User(1)])
    await cog.on_message(msg)
    await _drain(cog)
    run_mock.assert_awaited_once()  # safe action -> runs immediately
    # Report the REAL RESULT, DON'T send the model's "ok" prose (avoids false claims)
    reply_text = msg.reply.call_args.args[0]
    assert "✅" in reply_text and "welcome" in reply_text.lower()
    # remember stores the real result, not "ok"
    assert stub.remember.call_args.kwargs["assistant_text"] != "ok"


async def _confirm_channel():
    """Fake channel: each send() returns its own 'message' with .edit (to verify old buttons get disabled)."""
    sent = []

    async def send(content, view=None):
        m = SimpleNamespace(id=len(sent) + 1, edit=AsyncMock(), view=view)
        sent.append(m)
        return m

    return SimpleNamespace(id=10, send=send), sent


@pytest.mark.asyncio
async def test_send_confirm_supersedes_old_same_target():
    # Change a destructive command of the same kind + same person (e.g. timeout 5m->10m) -> the OLD button is disabled.
    cog = _cog()
    channel, sent = await _confirm_channel()
    msg = SimpleNamespace(channel=channel)
    p5 = PendingAction(
        "timeout", True, "Timeout 1 person 5 minutes", {"target_ids": [9], "minutes": 5}
    )
    p10 = PendingAction(
        "timeout", True, "Timeout 1 person 10 minutes", {"target_ids": [9], "minutes": 10}
    )
    await cog._send_confirm(msg, p5)
    await cog._send_confirm(msg, p10)
    sent[0].edit.assert_awaited_once()  # the 5m button is edited to "replaced"
    assert "replaced" in sent[0].edit.call_args.kwargs.get("content", "").lower()
    sent[1].edit.assert_not_awaited()  # the 10m button stays intact


@pytest.mark.asyncio
async def test_send_confirm_keeps_old_for_different_target():
    # Different person -> DON'T touch the old button (timeout A then timeout B = 2 independent buttons).
    cog = _cog()
    channel, sent = await _confirm_channel()
    msg = SimpleNamespace(channel=channel)
    pa = PendingAction("timeout", True, "Timeout A", {"target_ids": [1], "minutes": 5})
    pb = PendingAction("timeout", True, "Timeout B", {"target_ids": [2], "minutes": 5})
    await cog._send_confirm(msg, pa)
    await cog._send_confirm(msg, pb)
    sent[0].edit.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirm_resolve_clears_tracking():
    # Pressing ✅/❌ -> remove from the tracking book so a later command does NOT overwrite an already-handled message.
    cog = _cog()
    channel, sent = await _confirm_channel()
    msg = SimpleNamespace(channel=channel)
    p = PendingAction(
        "timeout", True, "Timeout 1 person 5 minutes", {"target_ids": [9], "minutes": 5}
    )
    await cog._send_confirm(msg, p)
    key = cog._confirm_key(10, p)
    assert key in cog._pending_confirms
    sent[
        0
    ].view._resolve()  # simulate PRESSING the button -> view calls on_resolve -> removes from the book
    assert key not in cog._pending_confirms


@pytest.mark.asyncio
async def test_on_message_destructive_sends_confirm(monkeypatch):
    cid = uuid.uuid4()
    danger = PendingAction("ban", True, "Ban 1 person", {"target_ids": [9], "reason": ""})
    stub = MagicMock()
    stub.respond = AsyncMock(return_value=(cid, "ok", [danger]))
    stub.remember = AsyncMock()
    _patch(monkeypatch, stub)
    run_mock = AsyncMock()
    monkeypatch.setattr(agent_mod, "run_action", run_mock)
    cog = _cog()
    msg = _Msg(author=_User(2), mentions=[_User(1)])
    await cog.on_message(msg)
    await _drain(cog)
    msg.channel.send.assert_awaited_once()  # sends the confirm button
    run_mock.assert_not_awaited()  # NOT executed yet (waiting for ✅)


class _HistMsg:
    """Fake message for channel.history()."""

    def __init__(self, who, text):
        self.clean_content = text
        self.author = SimpleNamespace(display_name=who)


class _HistChannel:
    def __init__(self, msgs, *, raises=False):
        self._msgs = msgs
        self._raises = raises

    def history(self, *, limit, before):
        chan = self

        class _It:
            def __aiter__(self_inner):
                self_inner._i = iter(chan._msgs)
                return self_inner

            async def __anext__(self_inner):
                if chan._raises:
                    raise agent_mod.discord.DiscordException("boom")
                try:
                    return next(self_inner._i)
                except StopIteration:
                    raise StopAsyncIteration

        return _It()


@pytest.mark.asyncio
async def test_collect_channel_context_orders_oldest_first():
    # history() returns newest->oldest; the helper must reverse it to oldest->newest + format 'Name: content'
    ch = _HistChannel([_HistMsg("An", "new message"), _HistMsg("Phong", "old message")])
    out = await agent_mod.collect_channel_context(ch, before=object())
    assert out == "Phong: old message\nAn: new message"


@pytest.mark.asyncio
async def test_collect_channel_context_swallows_errors():
    ch = _HistChannel([], raises=True)
    assert await agent_mod.collect_channel_context(ch, before=object()) == ""
