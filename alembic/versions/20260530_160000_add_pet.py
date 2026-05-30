"""Add pet tables: guild_pet, user_pet_cooldown.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-05-30 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "guild_pet",
        sa.Column("guild_id", sa.UUID(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("name", sa.String(length=32), nullable=False, server_default="Pet"),
        sa.Column("hunger", sa.Integer(), nullable=False, server_default=sa.text("100")),
        sa.Column("happiness", sa.Integer(), nullable=False, server_default=sa.text("100")),
        sa.Column("xp", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_decay_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("feed_cost", sa.Integer(), nullable=False, server_default=sa.text("10")),
        sa.Column("feed_amount", sa.Integer(), nullable=False, server_default=sa.text("30")),
        sa.Column("play_amount", sa.Integer(), nullable=False, server_default=sa.text("30")),
        sa.Column("decay_per_day", sa.Integer(), nullable=False, server_default=sa.text("20")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("guild_id"),
        sa.CheckConstraint("hunger >= 0 AND hunger <= 100", name="ck_pet_hunger_range"),
        sa.CheckConstraint("happiness >= 0 AND happiness <= 100", name="ck_pet_happiness_range"),
        sa.CheckConstraint("xp >= 0", name="ck_pet_xp_nonneg"),
        sa.CheckConstraint("feed_cost >= 0", name="ck_pet_feed_cost_nonneg"),
        sa.CheckConstraint("feed_amount >= 0", name="ck_pet_feed_amount_nonneg"),
        sa.CheckConstraint("play_amount >= 0", name="ck_pet_play_amount_nonneg"),
        sa.CheckConstraint("decay_per_day >= 0", name="ck_pet_decay_nonneg"),
    )
    op.create_table(
        "user_pet_cooldown",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("guild_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("last_play_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("guild_id", "user_id", name="uq_user_pet_cooldown"),
    )
    op.create_index("ix_user_pet_cooldown_guild_id", "user_pet_cooldown", ["guild_id"])


def downgrade() -> None:
    op.drop_index("ix_user_pet_cooldown_guild_id", table_name="user_pet_cooldown")
    op.drop_table("user_pet_cooldown")
    op.drop_table("guild_pet")
