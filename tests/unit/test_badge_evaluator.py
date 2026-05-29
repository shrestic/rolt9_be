from app.services.badges.evaluator import evaluate


def test_awards_newly_met_badges():
    new = evaluate({"level": 10, "longest_streak": 0, "balance": 0}, earned=set())
    keys = {b.key for b in new}
    assert keys == {"level_5", "level_10"}  # both thresholds met


def test_skips_already_earned():
    new = evaluate({"level": 10, "longest_streak": 0, "balance": 0}, earned={"level_5"})
    keys = {b.key for b in new}
    assert keys == {"level_10"}


def test_nothing_when_below_all_thresholds():
    new = evaluate({"level": 1, "longest_streak": 1, "balance": 50}, earned=set())
    assert new == []


def test_mixes_stats():
    new = evaluate({"level": 25, "longest_streak": 30, "balance": 10_000}, earned=set())
    keys = {b.key for b in new}
    assert keys == {
        "level_5",
        "level_10",
        "level_25",
        "streak_7",
        "streak_30",
        "wealth_1k",
        "wealth_10k",
    }


def test_missing_stat_defaults_to_zero():
    # An absent stat key must not crash; it counts as 0 (earns nothing).
    new = evaluate({"level": 5}, earned=set())
    assert {b.key for b in new} == {"level_5"}
