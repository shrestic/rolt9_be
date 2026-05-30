"""Add karma tables: guild_karma_config, user_karma, karma_grant.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-05-30 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "guild_karma_config",
        sa.Column("guild_id", sa.UUID(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("guild_id"),
    )
    op.create_table(
        "user_karma",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("guild_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("guild_id", "user_id", name="uq_user_karma_guild_user"),
        sa.CheckConstraint("points >= 0", name="ck_user_karma_points_nonneg"),
    )
    op.create_index("ix_user_karma_guild_id", "user_karma", ["guild_id"])
    op.create_index("ix_user_karma_leaderboard", "user_karma", ["guild_id", "points"])
    op.create_table(
        "karma_grant",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("guild_id", sa.UUID(), nullable=False),
        sa.Column("giver_id", sa.BigInteger(), nullable=False),
        sa.Column("receiver_id", sa.BigInteger(), nullable=False),
        sa.Column("last_granted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("guild_id", "giver_id", "receiver_id", name="uq_karma_grant_pair"),
    )
    op.create_index("ix_karma_grant_guild", "karma_grant", ["guild_id"])


def downgrade() -> None:
    op.drop_index("ix_karma_grant_guild", table_name="karma_grant")
    op.drop_table("karma_grant")
    op.drop_index("ix_user_karma_leaderboard", table_name="user_karma")
    op.drop_index("ix_user_karma_guild_id", table_name="user_karma")
    op.drop_table("user_karma")
    op.drop_table("guild_karma_config")
