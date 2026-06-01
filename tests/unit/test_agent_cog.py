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
        self.resolved = resolved  # tin được reply tới (Message) nếu cache có


class _Typing:
    """Async context manager rỗng giả cho channel.typing()."""

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
        self.add_reaction = AsyncMock()  # để test reaction ⏳ khi bị throttle


# ---------- pure helpers ----------


def test_is_addressed_by_mention():
    bot = _User(1)
    assert is_addressed(_Msg(mentions=[_User(1)]), bot) is True
    assert is_addressed(_Msg(mentions=[_User(2)]), bot) is False


def test_is_addressed_by_reply_to_bot_only():
    bot = _User(1)
    # reply vào TIN CỦA BOT -> True
    ref_bot = _Ref(99, resolved=SimpleNamespace(author=_User(1)))
    assert is_addressed(_Msg(reference=ref_bot), bot) is True
    # reply vào tin NGƯỜI KHÁC -> False (đây là con bug cũ: nhận mọi reply)
    ref_other = _Ref(99, resolved=SimpleNamespace(author=_User(2)))
    assert is_addressed(_Msg(reference=ref_other), bot) is False
    # reply nhưng không resolve được -> không tự nhận (tránh rep nhầm)
    assert is_addressed(_Msg(reference=_Ref(99)), bot) is False
    assert is_addressed(_Msg(content="chào mọi người"), bot) is False


def test_is_addressed_name_prefix_word_boundary():
    bot = _User(1, name="rolt9")
    assert is_addressed(_Msg(content="rolt9 ơi"), bot) is True
    assert is_addressed(_Msg(content="rolt9000 là gì"), bot) is False  # khớp nhầm -> chặn


def test_is_addressed_by_name_text():
    bot = _User(1, name="rolt9")
    # gõ "@rolt9 ..." dạng text (mention không thành) vẫn được nhận
    assert is_addressed(_Msg(content="@rolt9 mấy giờ rồi?"), bot) is True
    assert is_addressed(_Msg(content="rolt9 ơi giúp tí"), bot) is True
    assert is_addressed(_Msg(content="nói chuyện bình thường"), bot) is False


def test_is_addressed_by_clean_content_role_render():
    bot = _User(1, name="rolt9")
    # Mention ROLE -> content có "<@&..>" nhưng clean_content render thành "@rolt9"
    msg = _Msg(content="<@&999> mấy giờ", clean_content="@rolt9 mấy giờ")
    assert is_addressed(msg, bot) is True


def test_is_addressed_by_bot_role_mention():
    bot = _User(1, name="rolt9")
    role = SimpleNamespace(id=999)
    msg = _Msg(
        content="<@&999> hi", clean_content="@SomeRole hi", role_mentions=[role], me_role_ids=(999,)
    )
    assert is_addressed(msg, bot) is True


class _Member:
    """Thành viên giả cho guild.members trong test tag_known_members."""

    def __init__(self, id, name=None, global_name=None):
        self.id = id
        self.name = name
        self.global_name = global_name


def _guild_with(members):
    return SimpleNamespace(members=members)


def test_tag_known_members_username_to_mention():
    from app.bot.cogs.agent import tag_known_members

    g = _guild_with([_Member(42, name="thinh.nguyen2", global_name="Đạt")])
    # tên chữ trơn trong câu -> đổi thành <@id> để ping
    out = tag_known_members("Đạt = thằng thinh.nguyen2 đấy", g, bot_id=1)
    assert "<@42>" in out
    assert "thinh.nguyen2" not in out  # username đã được thay


def test_tag_known_members_fixes_fabricated_mention():
    from app.bot.cogs.agent import tag_known_members

    g = _guild_with([_Member(42, name="thinh.nguyen2", global_name="Đạt")])
    # Model BỊA '<@thinh.nguyen2>' (Discord ko render vì cần ID số) -> phải sửa thành '<@42>'.
    out = tag_known_members("Đạt = thằng <@thinh.nguyen2> tên thật Đạt", g, bot_id=1)
    assert "<@42>" in out
    assert "<@thinh.nguyen2>" not in out
    assert out.count("<@42>") == 1  # không nhân đôi


def test_tag_known_members_fixes_fabricated_mention_bang_form():
    from app.bot.cogs.agent import tag_known_members

    g = _guild_with([_Member(42, name="thinh.nguyen2")])
    out = tag_known_members("ê <@!thinh.nguyen2> ơi", g, bot_id=1)
    assert out == "ê <@42> ơi"


def test_tag_known_members_skips_short_common_names():
    from app.bot.cogs.agent import tag_known_members

    # global_name 'Đạt' (3 ký tự, thuần chữ) KHÔNG đủ đặc trưng -> không tag (tránh ping nhầm).
    g = _guild_with([_Member(7, name="abc", global_name="Đạt")])
    out = tag_known_members("Hôm nay Đạt được mùa", g, bot_id=1)
    assert out == "Hôm nay Đạt được mùa"  # giữ nguyên


def test_tag_known_members_idempotent_and_no_double_tag():
    from app.bot.cogs.agent import tag_known_members

    g = _guild_with([_Member(42, name="thinh.nguyen2")])
    # đã có sẵn <@42> -> không tự chèn thêm
    assert tag_known_members("chào <@42> nhé", g, bot_id=1) == "chào <@42> nhé"
    # không đụng vào mention sẵn của người khác / username nằm trong <@...>
    out = tag_known_members("ping thinh.nguyen2 đi", g, bot_id=1)
    assert out.count("<@42>") == 1


def test_tag_known_members_skips_bot_itself():
    from app.bot.cogs.agent import tag_known_members

    g = _guild_with([_Member(1, name="rolt9.bot")])
    out = tag_known_members("gọi rolt9.bot xem", g, bot_id=1)
    assert "<@1>" not in out  # chính bot -> không tag


def test_tag_known_members_strips_fabricated_bot_mention():
    from app.bot.cogs.agent import tag_known_members

    # Model tự bịa '<@rolt9>' (mention chính bot, không phải id số) -> Discord ra chữ rác.
    # Phải bỏ cặp '<@ >', để lại 'rolt9' (không tag chính bot).
    g = _guild_with([_Member(1, name="rolt9")])
    out = tag_known_members("Alo alo, <@rolt9>! Mày gọi gì đấy?", g, bot_id=1)
    assert "<@rolt9>" not in out
    assert "rolt9" in out  # còn lại tên thường


def test_tag_known_members_strips_any_unknown_fabricated_mention():
    from app.bot.cogs.agent import tag_known_members

    # Tên không có trong guild members mà model vẫn bịa '<@ai_do>' -> dọn về chữ thường.
    g = _guild_with([])
    out = tag_known_members("hỏi <@ai_do> đi nha", g, bot_id=1)
    assert out == "hỏi ai_do đi nha"


def test_tag_known_members_keeps_valid_id_and_role_mentions():
    from app.bot.cogs.agent import tag_known_members

    g = _guild_with([_Member(42, name="thinh.nguyen2")])
    # '<@123>' (id số) và '<@&999>' (role) đều HỢP LỆ -> giữ nguyên, không bị dọn nhầm.
    out = tag_known_members("chào <@123> và role <@&999> nhé", g, bot_id=1)
    assert "<@123>" in out and "<@&999>" in out


def test_cooldown_tracker():
    t = CooldownTracker(AGENT_COOLDOWN)
    assert t.ready(7, 42, now=100.0) is True
    t.mark(7, 42, now=100.0)
    assert t.ready(7, 42, now=100.0 + AGENT_COOLDOWN - 1) is False
    assert t.ready(7, 42, now=100.0 + AGENT_COOLDOWN + 1) is True


def test_cooldown_tracker_scoped_by_guild():
    # Cùng 1 user nhưng khác guild -> cooldown độc lập, không chặn nhầm chéo server.
    t = CooldownTracker(AGENT_COOLDOWN)
    t.mark(7, 42, now=100.0)  # user 42 ở guild 7
    assert t.ready(7, 42, now=100.0) is False  # cùng (guild, user) -> đang cooldown
    assert t.ready(8, 42, now=100.0) is True  # cùng user, guild khác -> KHÔNG bị chặn


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
    """Đợi pool worker xử lý xong toàn bộ hàng đợi (on_message giờ chỉ XẾP HÀNG,
    worker xử lý bất đồng bộ) — gọi trước khi assert kết quả respond/reply."""
    await cog._queue.join()


@pytest.mark.asyncio
async def test_on_message_replies_and_remembers(monkeypatch):
    cid = uuid.uuid4()
    stub = MagicMock()
    stub.respond = AsyncMock(return_value=(cid, "trả lời", []))
    stub.remember = AsyncMock()
    _patch(monkeypatch, stub)
    cog = _cog()
    msg = _Msg(author=_User(2), mentions=[_User(1)])
    await cog.on_message(msg)
    await _drain(cog)
    msg.reply.assert_awaited_once()
    stub.respond.assert_awaited_once()
    stub.remember.assert_awaited_once()
    # bot_message_id lấy từ tin đã gửi (555)
    assert stub.remember.call_args.kwargs["bot_message_id"] == 555
    # cog gom snapshot server (member_count + roles trừ @everyone) truyền vào respond
    snap = stub.respond.call_args.kwargs["server_snapshot"]
    assert snap["member_count"] == 5
    assert snap["roles"] == ["Mod"]


@pytest.mark.asyncio
async def test_on_message_ignores_not_addressed(monkeypatch):
    stub = MagicMock()
    stub.respond = AsyncMock()
    _patch(monkeypatch, stub)
    cog = _cog()
    await cog.on_message(_Msg(author=_User(2)))  # không mention, không reply
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
    stub.respond = AsyncMock(return_value=None)  # agent off / sai kênh
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
    stub.respond = AsyncMock(side_effect=ValueError("hết budget"))
    _patch(monkeypatch, stub)
    cog = _cog()
    msg = _Msg(author=_User(2), mentions=[_User(1)])
    await cog.on_message(msg)
    await _drain(cog)
    msg.reply.assert_awaited_once()
    assert "❌" in msg.reply.call_args.args[0]


@pytest.mark.asyncio
async def test_on_message_marks_cooldown_before_processing(monkeypatch):
    # Mark cooldown NGAY (trước respond): dù respond trả None / chậm, tin thứ 2 vẫn bị chặn.
    stub = MagicMock()
    stub.respond = AsyncMock(return_value=None)  # vd agent off / sai kênh
    stub.remember = AsyncMock()
    _patch(monkeypatch, stub)
    cog = _cog()
    u = _User(2)
    await cog.on_message(_Msg(author=u, mentions=[_User(1)]))
    await cog.on_message(_Msg(author=u, mentions=[_User(1)]))  # ngay sau -> cooldown chặn
    await _drain(cog)
    assert stub.respond.await_count == 1  # lần 2 bị chặn dù lần 1 không trả lời


@pytest.mark.asyncio
async def test_on_message_per_user_cap_drops_overflow(monkeypatch):
    # 1 người chỉ được xếp tối đa AGENT_PER_USER_MAX lượt (đang chờ + đang chạy). Lượt thứ 3
    # bị bỏ (⏳) NGAY, không nhồi đầy hàng đợi. Tắt cooldown để cô lập đúng cửa per-user.
    import asyncio

    gate = asyncio.Event()
    cid = uuid.uuid4()

    async def slow_respond(**kw):
        await gate.wait()  # giữ các lượt đầu "đang chạy" để chiếm slot pending
        return (cid, "ok", [])

    stub = MagicMock()
    stub.respond = AsyncMock(side_effect=slow_respond)
    stub.remember = AsyncMock()
    _patch(monkeypatch, stub)
    cog = _cog()
    cog.cooldown = CooldownTracker(0.0)  # tắt cooldown -> chỉ còn cửa per-user
    u = _User(2)
    await cog.on_message(_Msg(author=u, mentions=[_User(1)]))  # lượt 1 -> pending=1
    await cog.on_message(_Msg(author=u, mentions=[_User(1)]))  # lượt 2 -> pending=2 (đầy slot)
    msg3 = _Msg(author=u, mentions=[_User(1)])
    await cog.on_message(msg3)  # lượt 3 -> pending đã 2 -> bị bỏ
    gate.set()
    await _drain(cog)
    assert stub.respond.await_count == 2  # chỉ 2 lượt đầu được xử lý
    msg3.add_reaction.assert_awaited_once_with("⏳")  # lượt 3 bị tiết chế


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
    msg2 = _Msg(author=u, mentions=[_User(1)])  # ngay lập tức -> cooldown chặn
    await cog.on_message(msg2)
    await _drain(cog)
    assert stub.respond.await_count == 1
    msg2.add_reaction.assert_awaited_once_with("⏳")  # báo bị throttle bằng reaction ⏳


@pytest.mark.asyncio
async def test_on_message_many_distinct_users_all_processed_no_throttle(monkeypatch):
    # KỊCH BẢN LO NGẠI: nhiều người KHÁC NHAU cùng mention bot trong thời gian ngắn.
    # Throttle là PER-USER (cooldown + per-user cap theo (guild,user)) -> người khác nhau
    # KHÔNG chặn nhau; tất cả được XẾP HÀNG và xử lý hết, không ai bị ⏳.
    cid = uuid.uuid4()
    stub = MagicMock()
    stub.respond = AsyncMock(return_value=(cid, "ok", []))
    stub.remember = AsyncMock()
    _patch(monkeypatch, stub)
    cog = _cog()
    # 10 người khác nhau (id 100..109), mỗi người 1 lệnh — nhiều hơn 3 worker để buộc xếp hàng.
    msgs = [_Msg(author=_User(100 + i), mentions=[_User(1)]) for i in range(10)]
    for m in msgs:
        await cog.on_message(m)
    await _drain(cog)
    assert stub.respond.await_count == 10  # cả 10 đều được xử lý (xếp hàng, không drop)
    for m in msgs:
        m.add_reaction.assert_not_awaited()  # KHÔNG ai bị tiết chế ⏳


@pytest.mark.asyncio
async def test_on_message_concurrent_bans_all_call_tool(monkeypatch):
    # Nhiều người khác nhau cùng bảo "ban" trong thời gian ngắn -> CẢ NHÓM đều gọi được tool
    # (mỗi lượt stage 1 action phá -> gửi nút xác nhận). Không ai bị bỏ vì throttle.
    cid = uuid.uuid4()
    danger = PendingAction("ban", True, "Ban 1 người", {"target_ids": [9], "reason": ""})
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
    assert stub.respond.await_count == 6  # cả 6 lượt agent chạy (gọi tool ban)
    assert sum(m.channel.send.await_count for m in msgs) == 6  # mỗi người 1 nút xác nhận
    run_mock.assert_not_awaited()  # phá -> chờ ✅, chưa execute
    for m in msgs:
        m.add_reaction.assert_not_awaited()  # không ai bị ⏳


@pytest.mark.asyncio
async def test_on_message_same_user_spam_bans_throttled(monkeypatch):
    # NGƯỢC LẠI: CÙNG 1 người spam "ban" liên tục -> cooldown chỉ cho 1 lượt qua,
    # các lượt sau bị ⏳ (đây là hành vi chống spam MONG MUỐN, không phải bug).
    cid = uuid.uuid4()
    danger = PendingAction("ban", True, "Ban 1 người", {"target_ids": [9], "reason": ""})
    stub = MagicMock()
    stub.respond = AsyncMock(return_value=(cid, "ok", [danger]))
    stub.remember = AsyncMock()
    _patch(monkeypatch, stub)
    monkeypatch.setattr(agent_mod, "run_action", AsyncMock())
    cog = _cog()
    u = _User(2)
    spam = [_Msg(author=u, mentions=[_User(1)]) for _ in range(5)]
    for m in spam:
        await cog.on_message(m)  # bắn liền tay trong cùng cửa sổ cooldown
    await _drain(cog)
    assert stub.respond.await_count == 1  # chỉ lượt đầu của họ được xử lý
    throttled = sum(m.add_reaction.await_count for m in spam[1:])
    assert throttled == 4  # 4 lượt spam sau đều bị ⏳


@pytest.mark.asyncio
async def test_on_message_overload_sheds_load_no_loss_no_crash(monkeypatch):
    # KỊCH BẢN XẤU NHẤT: cả server spam liên tục không nghỉ, nhiều hơn sức chứa hàng đợi.
    # Bảo đảm 3 tính chất: (1) KHÔNG sập/treo; (2) KHÔNG mất tin — mỗi tin HOẶC được xử lý
    # HOẶC bị ⏳; (3) tin lọt vào hàng đợi VẪN được xử lý (respond/reply chạy đủ).
    import asyncio

    from app.bot.cogs.agent import AGENT_QUEUE_MAX, AGENT_WORKERS

    gate = asyncio.Event()
    cid = uuid.uuid4()

    async def slow(**kw):
        await gate.wait()  # giữ worker bận để hàng đợi dồn lại -> ép chạm trần
        return (cid, "trả lời", [])

    stub = MagicMock()
    stub.respond = AsyncMock(side_effect=slow)
    stub.remember = AsyncMock()
    _patch(monkeypatch, stub)
    cog = _cog()
    cog.cooldown = CooldownTracker(0.0)  # tắt cooldown -> cô lập đúng cửa "hàng đợi đầy"
    # Mỗi người KHÁC NHAU (bỏ qua cooldown + per-user) để dồn được tối đa vào hàng đợi toàn cục.
    total = AGENT_WORKERS + AGENT_QUEUE_MAX + 8  # dư 8 người -> chắc chắn tràn
    msgs = [_Msg(author=_User(1000 + i), mentions=[_User(1)]) for i in range(total)]
    for m in msgs:
        await cog.on_message(m)  # (1) bắn dồn không nghỉ — không được raise/treo
    gate.set()
    await _drain(cog)

    dropped = sum(1 for m in msgs if m.add_reaction.await_count > 0)  # bị ⏳
    processed = sum(1 for m in msgs if m.reply.await_count > 0)  # đã trả lời (gọi respond xong)
    assert dropped >= 1  # (1+3) có shed khi quá tải -> hàng đợi KHÔNG phình vô hạn
    assert dropped + processed == total  # (2) KHÔNG mất tin: mỗi tin hoặc xử lý hoặc ⏳
    assert processed >= AGENT_QUEUE_MAX  # (3) phần lớn vẫn được xử lý đầy đủ (gọi respond)


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
    assert confirm_perm_ok("ban", d) is True  # cần ban_members -> có
    assert confirm_perm_ok("create_role", d) is False  # cần manage_roles -> không


@pytest.mark.asyncio
async def test_on_message_executes_safe_action(monkeypatch):
    cid = uuid.uuid4()
    safe = PendingAction(
        "toggle_plugin", False, "Bật welcome", {"plugin": "welcome", "enabled": True}
    )
    stub = MagicMock()
    stub.respond = AsyncMock(return_value=(cid, "ok", [safe]))
    stub.remember = AsyncMock()
    _patch(monkeypatch, stub)
    run_mock = AsyncMock(return_value="Đã bật welcome.")
    monkeypatch.setattr(agent_mod, "run_action", run_mock)
    cog = _cog()
    msg = _Msg(author=_User(2), mentions=[_User(1)])
    await cog.on_message(msg)
    await _drain(cog)
    run_mock.assert_awaited_once()  # action an toàn -> chạy ngay
    # Báo theo KẾT QUẢ THẬT, KHÔNG gửi prose "ok" của model (tránh khai khống)
    reply_text = msg.reply.call_args.args[0]
    assert "✅" in reply_text and "welcome" in reply_text.lower()
    # remember lưu kết quả thật, không lưu "ok"
    assert stub.remember.call_args.kwargs["assistant_text"] != "ok"


@pytest.mark.asyncio
async def test_on_message_destructive_sends_confirm(monkeypatch):
    cid = uuid.uuid4()
    danger = PendingAction("ban", True, "Ban 1 người", {"target_ids": [9], "reason": ""})
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
    msg.channel.send.assert_awaited_once()  # gửi nút xác nhận
    run_mock.assert_not_awaited()  # CHƯA execute (chờ ✅)


class _HistMsg:
    """Tin nhắn giả cho channel.history()."""

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
    # history() trả mới->cũ; helper phải đảo lại thành cũ->mới + format 'Tên: nội dung'
    ch = _HistChannel([_HistMsg("An", "tin moi"), _HistMsg("Phong", "tin cu")])
    out = await agent_mod.collect_channel_context(ch, before=object())
    assert out == "Phong: tin cu\nAn: tin moi"


@pytest.mark.asyncio
async def test_collect_channel_context_swallows_errors():
    ch = _HistChannel([], raises=True)
    assert await agent_mod.collect_channel_context(ch, before=object()) == ""
