"""Add mini-games config table: guild_minigame_config.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-05-30 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "guild_minigame_config",
        sa.Column("guild_id", sa.UUID(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("min_bet", sa.Integer(), nullable=False, server_default=sa.text("10")),
        sa.Column("max_bet", sa.Integer(), nullable=False, server_default=sa.text("10000")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("guild_id"),
        sa.CheckConstraint("min_bet >= 1", name="ck_minigame_min_bet_pos"),
        sa.CheckConstraint("max_bet >= 1", name="ck_minigame_max_bet_pos"),
        sa.CheckConstraint("min_bet <= max_bet", name="ck_minigame_bet_range"),
    )


def downgrade() -> None:
    op.drop_table("guild_minigame_config")
