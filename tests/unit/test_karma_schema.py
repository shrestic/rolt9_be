from app.schemas.karma import KarmaLeaderboardEntryOut, KarmaSettings


def test_settings_defaults_disabled():
    assert KarmaSettings().enabled is False


def test_leaderboard_entry_shape():
    e = KarmaLeaderboardEntryOut(rank=1, user_id="123", points=5)
    assert e.user_id == "123"
    assert e.points == 5
