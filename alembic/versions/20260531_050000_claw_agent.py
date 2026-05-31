"""Claw Agent: agent_message, guild_user_memory, guild_ai_config agent cols

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-05-31 05:00:00.000000
"""

from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d6e7f8a9b0c1"
down_revision: Union[str, None] = "c5d6e7f8a9b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "guild_ai_config",
        sa.Column("agent_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("guild_ai_config", sa.Column("agent_channel_id", sa.BigInteger(), nullable=True))

    op.create_table(
        "agent_message",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("guild_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("discord_message_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.CheckConstraint("role in ('user','assistant')", name="ck_agent_message_role"),
    )
    op.create_index("ix_agent_message_guild_id", "agent_message", ["guild_id"])
    op.create_index("ix_agent_message_conversation_id", "agent_message", ["conversation_id"])
    op.create_index(
        "ix_agent_message_discord_message_id", "agent_message", ["discord_message_id"]
    )

    op.create_table(
        "guild_user_memory",
        sa.Column("guild_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_discord_id", sa.BigInteger(), nullable=False),
        sa.Column("facts", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("guild_id", "user_discord_id"),
    )


def downgrade() -> None:
    op.drop_table("guild_user_memory")
    op.drop_index("ix_agent_message_discord_message_id", table_name="agent_message")
    op.drop_index("ix_agent_message_conversation_id", table_name="agent_message")
    op.drop_index("ix_agent_message_guild_id", table_name="agent_message")
    op.drop_table("agent_message")
    op.drop_column("guild_ai_config", "agent_channel_id")
    op.drop_column("guild_ai_config", "agent_enabled")
