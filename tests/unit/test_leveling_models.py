import uuid

import pytest

from app.models.guild_leveling_config import GuildLevelingConfig
from app.models.guild_rank_card_theme import GuildRankCardTheme
from app.models.level_role_reward import LevelRoleReward
from app.models.user_rank_card_theme import UserRankCardTheme
from app.models.user_xp import UserXp


@pytest.mark.asyncio
async def test_can_persist_all_leveling_models(db_session):
    gid = uuid.uuid4()
    from app.models.guild import Guild

    db_session.add(Guild(id=gid, discord_id=1, name="g", icon_url=None, is_active=True))
    await db_session.commit()

    db_session.add_all(
        [
            GuildLevelingConfig(guild_id=gid),
            UserXp(guild_id=gid, user_id=42, total_xp=0),
            LevelRoleReward(guild_id=gid, level=5, role_id=999),
            GuildRankCardTheme(guild_id=gid),
            UserRankCardTheme(guild_id=gid, user_id=42),
        ]
    )
    await db_session.commit()

    cfg = await db_session.get(GuildLevelingConfig, gid)
    assert cfg is not None
    assert cfg.enabled is False
    assert cfg.xp_min == 15
    assert cfg.xp_max == 25
    assert cfg.cooldown_seconds == 60
    assert cfg.min_message_length == 4
    assert cfg.ignore_emoji_only is True
    assert cfg.ignore_link_only is True
    assert cfg.notification_mode == "channel"
    assert cfg.level_role_mode == "replacing"

    theme = await db_session.get(GuildRankCardTheme, gid)
    assert theme.bg_type == "gradient"
    assert theme.bg_color_1 == "#0f172a"
