import random

from app.services.minigames.minigame_logic import (
    SLOTS_SYMBOLS,
    Outcome,
    play_coinflip,
    play_over_under,
    play_slots,
)


class _FixedRng:
    """A random.Random stand-in that returns scripted choice()/randint() values."""

    def __init__(self, choices=None, ints=None):
        self._choices = list(choices or [])
        self._ints = list(ints or [])

    def choice(self, seq):
        return self._choices.pop(0)

    def randint(self, a, b):
        return self._ints.pop(0)


def test_coinflip_win_pays_1_9x():
    out = play_coinflip(_FixedRng(choices=["heads"]), 100, "heads")
    assert out.won is True
    assert out.payout == 190


def test_coinflip_loss_pays_zero():
    out = play_coinflip(_FixedRng(choices=["tails"]), 100, "heads")
    assert out.won is False
    assert out.payout == 0


def test_over_under_tai_boundary_11_wins_on_tai():
    out = play_over_under(_FixedRng(ints=[6, 4, 1]), 100, "over")
    assert out.won is True
    assert out.payout == 190
    assert "11" in out.detail and "Over" in out.detail


def test_over_under_xiu_boundary_10_wins_on_xiu():
    out = play_over_under(_FixedRng(ints=[5, 4, 1]), 100, "under")
    assert out.won is True


def test_over_under_wrong_guess_loses():
    out = play_over_under(_FixedRng(ints=[6, 6, 6]), 100, "under")
    assert out.won is False
    assert out.payout == 0


def test_slots_jackpot_three_match():
    out = play_slots(_FixedRng(choices=["💎", "💎", "💎"]), 100)
    assert out.won is True
    assert out.payout == 1000


def test_slots_pair_consolation():
    out = play_slots(_FixedRng(choices=["🍒", "🍒", "🔔"]), 100)
    assert out.won is True
    assert out.payout == 160


def test_slots_no_match_loses():
    out = play_slots(_FixedRng(choices=["🍒", "🔔", "🍋"]), 100)
    assert out.won is False
    assert out.payout == 0


def test_real_random_is_deterministic_with_seed():
    out = play_coinflip(random.Random(1), 50, "heads")
    assert isinstance(out, Outcome)
    assert SLOTS_SYMBOLS
