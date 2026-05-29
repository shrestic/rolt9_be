"""Add leveling tables: guild_leveling_config, user_xp, level_role_reward,
guild_rank_card_theme, user_rank_card_theme.

Revision ID: a1b2c3d4e5f6
Revises: 3322d313cac5
Create Date: 2026-05-27 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "3322d313cac5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


notification_mode_enum = sa.Enum("channel", "dm", "off", name="notification_mode")
level_role_mode_enum = sa.Enum("stacking", "replacing", name="level_role_mode")
bg_type_enum = sa.Enum("solid", "gradient", name="bg_type")


def upgrade() -> None:
    bind = op.get_bind()
    notification_mode_enum.create(bind, checkfirst=True)
    level_role_mode_enum.create(bind, checkfirst=True)
    bg_type_enum.create(bind, checkfirst=True)

    op.create_table(
        "guild_leveling_config",
        sa.Column("guild_id", sa.UUID(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("xp_min", sa.Integer(), nullable=False, server_default=sa.text("15")),
        sa.Column("xp_max", sa.Integer(), nullable=False, server_default=sa.text("25")),
        sa.Column("cooldown_seconds", sa.Integer(), nullable=False, server_default=sa.text("60")),
        sa.Column("min_message_length", sa.Integer(), nullable=False, server_default=sa.text("4")),
        sa.Column("ignore_emoji_only", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("ignore_link_only", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("ignored_channel_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("ignored_role_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column(
            "notification_mode",
            sa.Enum(name="notification_mode", create_type=False),
            nullable=False,
            server_default="channel",
        ),
        sa.Column("notification_channel_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "level_role_mode",
            sa.Enum(name="level_role_mode", create_type=False),
            nullable=False,
            server_default="replacing",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("guild_id"),
        sa.CheckConstraint("xp_min >= 1", name="ck_guild_leveling_config_xp_min_positive"),
        sa.CheckConstraint("xp_max >= 1", name="ck_guild_leveling_config_xp_max_positive"),
        sa.CheckConstraint("xp_min <= xp_max", name="ck_guild_leveling_config_xp_range"),
        sa.CheckConstraint(
            "cooldown_seconds >= 0", name="ck_guild_leveling_config_cooldown_nonneg"
        ),
        sa.CheckConstraint(
            "min_message_length >= 0",
            name="ck_guild_leveling_config_min_msg_len_nonneg",
        ),
    )

    op.create_table(
        "user_xp",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("guild_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("total_xp", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_xp_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("guild_id", "user_id", name="uq_user_xp_guild_user"),
    )
    op.create_index("ix_user_xp_guild_id", "user_xp", ["guild_id"], unique=False)
    op.create_index("ix_user_xp_leaderboard", "user_xp", ["guild_id", "total_xp"], unique=False)

    op.create_table(
        "level_role_reward",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("guild_id", sa.UUID(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("guild_id", "level", name="uq_level_role_reward_guild_level"),
    )
    op.create_index(
        "ix_level_role_reward_guild_level", "level_role_reward", ["guild_id", "level"], unique=False
    )

    op.create_table(
        "guild_rank_card_theme",
        sa.Column("guild_id", sa.UUID(), nullable=False),
        sa.Column("bg_type", sa.Enum(name="bg_type", create_type=False), nullable=False, server_default="gradient"),
        sa.Column("bg_color_1", sa.String(length=7), nullable=False, server_default="#0f172a"),
        sa.Column("bg_color_2", sa.String(length=7), nullable=False, server_default="#581c87"),
        sa.Column("accent_color", sa.String(length=7), nullable=False, server_default="#fbbf24"),
        sa.Column("text_color", sa.String(length=7), nullable=False, server_default="#ffffff"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("guild_id"),
    )

    op.create_table(
        "user_rank_card_theme",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("guild_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("bg_type", sa.Enum(name="bg_type", create_type=False), nullable=False, server_default="gradient"),
        sa.Column("bg_color_1", sa.String(length=7), nullable=False, server_default="#0f172a"),
        sa.Column("bg_color_2", sa.String(length=7), nullable=False, server_default="#581c87"),
        sa.Column("accent_color", sa.String(length=7), nullable=False, server_default="#fbbf24"),
        sa.Column("text_color", sa.String(length=7), nullable=False, server_default="#ffffff"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("guild_id", "user_id", name="uq_user_rank_card_theme_guild_user"),
    )
    op.create_index("ix_user_rank_card_theme_guild_id", "user_rank_card_theme", ["guild_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_user_rank_card_theme_guild_id", table_name="user_rank_card_theme")
    op.drop_table("user_rank_card_theme")
    op.drop_table("guild_rank_card_theme")
    op.drop_index("ix_level_role_reward_guild_level", table_name="level_role_reward")
    op.drop_table("level_role_reward")
    op.drop_index("ix_user_xp_leaderboard", table_name="user_xp")
    op.drop_index("ix_user_xp_guild_id", table_name="user_xp")
    op.drop_table("user_xp")
    op.drop_table("guild_leveling_config")

    bind = op.get_bind()
    bg_type_enum.drop(bind, checkfirst=True)
    level_role_mode_enum.drop(bind, checkfirst=True)
    notification_mode_enum.drop(bind, checkfirst=True)
