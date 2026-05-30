"""Add quests tables: guild_quest, user_quest_progress.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-05-30 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "guild_quest",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("guild_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("period", sa.String(length=16), nullable=False),
        sa.Column("objective_type", sa.String(length=32), nullable=False),
        sa.Column("target", sa.Integer(), nullable=False),
        sa.Column("reward_coins", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("target > 0", name="ck_quest_target_pos"),
        sa.CheckConstraint("reward_coins >= 0", name="ck_quest_reward_nonneg"),
    )
    op.create_index("ix_guild_quest_guild_id", "guild_quest", ["guild_id"])
    op.create_index("ix_guild_quest_enabled", "guild_quest", ["guild_id", "enabled"])
    op.create_table(
        "user_quest_progress",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("guild_id", sa.UUID(), nullable=False),
        sa.Column("quest_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("period_key", sa.String(length=16), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("claimed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["quest_id"], ["guild_quest.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("quest_id", "user_id", "period_key", name="uq_quest_progress"),
        sa.CheckConstraint("progress >= 0", name="ck_quest_progress_nonneg"),
    )
    op.create_index(
        "ix_quest_progress_member", "user_quest_progress", ["guild_id", "user_id", "period_key"]
    )


def downgrade() -> None:
    op.drop_index("ix_quest_progress_member", table_name="user_quest_progress")
    op.drop_table("user_quest_progress")
    op.drop_index("ix_guild_quest_enabled", table_name="guild_quest")
    op.drop_index("ix_guild_quest_guild_id", table_name="guild_quest")
    op.drop_table("guild_quest")
