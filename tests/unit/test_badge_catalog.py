from app.services.badges.catalog import BADGES, STAT_KEYS, BadgeDef, by_key


def test_badges_have_unique_keys():
    keys = [b.key for b in BADGES]
    assert len(keys) == len(set(keys)), "badge keys must be unique"


def test_every_badge_uses_a_known_stat():
    for b in BADGES:
        assert b.stat in STAT_KEYS, f"{b.key} uses unknown stat {b.stat}"


def test_by_key_roundtrips_and_misses():
    assert by_key("level_10").threshold == 10
    assert isinstance(by_key("level_10"), BadgeDef)
    assert by_key("nope") is None


def test_catalog_covers_expected_milestones():
    keys = {b.key for b in BADGES}
    assert {"level_5", "level_10", "level_25", "level_50"} <= keys
    assert {"streak_7", "streak_30", "streak_100", "streak_365"} <= keys
    assert {"wealth_1k", "wealth_10k", "wealth_100k"} <= keys
