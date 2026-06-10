"""Add welcome plugin table: guild_welcome_config.

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-05-31 02:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a3b4c5d6e7f8"
down_revision: Union[str, None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DEFAULT_WELCOME = "Welcome {user} to {server}! 🎉 You are member number {count}."
_DEFAULT_LEAVE = "{user} has left **{server}**. 👋"


def upgrade() -> None:
    op.create_table(
        "guild_welcome_config",
        sa.Column("guild_id", sa.UUID(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("channel_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "welcome_template", sa.String(length=1000), nullable=False, server_default=_DEFAULT_WELCOME
        ),
        sa.Column("ai_welcome", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("leave_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "leave_template", sa.String(length=1000), nullable=False, server_default=_DEFAULT_LEAVE
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("guild_id"),
    )


def downgrade() -> None:
    op.drop_table("guild_welcome_config")
