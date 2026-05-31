from app.bot.cogs.agent import AGENT_COOLDOWN, CooldownTracker, is_addressed


class _User:
    def __init__(self, id):
        self.id = id


class _Ref:
    def __init__(self, mid):
        self.message_id = mid


class _Msg:
    def __init__(self, *, mentions=None, reference=None):
        self.mentions = mentions or []
        self.reference = reference


def test_is_addressed_by_mention():
    bot = _User(1)
    assert is_addressed(_Msg(mentions=[_User(1)]), bot) is True
    assert is_addressed(_Msg(mentions=[_User(2)]), bot) is False


def test_is_addressed_by_reply_present():
    bot = _User(1)
    assert is_addressed(_Msg(reference=_Ref(99)), bot) is True
    assert is_addressed(_Msg(), bot) is False


def test_cooldown_tracker():
    t = CooldownTracker(AGENT_COOLDOWN)
    assert t.ready(42, now=100.0) is True
    t.mark(42, now=100.0)
    assert t.ready(42, now=100.0 + AGENT_COOLDOWN - 1) is False
    assert t.ready(42, now=100.0 + AGENT_COOLDOWN + 1) is True
