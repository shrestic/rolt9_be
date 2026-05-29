from app.schemas.badges import BadgeCatalogEntry, BadgeSettings


def test_badge_settings_defaults_disabled():
    assert BadgeSettings().enabled is False


def test_catalog_entry_shape():
    e = BadgeCatalogEntry(
        key="level_5",
        name="Tân binh",
        emoji="🥉",
        description="Đạt level 5",
        stat="level",
        threshold=5,
    )
    assert e.key == "level_5"
    assert e.threshold == 5
