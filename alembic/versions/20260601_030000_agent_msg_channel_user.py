"""Agent message: thêm channel_id + user_discord_id để nối cuộc theo (kênh, người)

Cho phép nối tiếp cuộc gần nhất khi user nhắn tiếp mà không reply (window-based,
xem AgentMessageRepository.latest_conversation). Cả hai nullable -> row cũ vẫn hợp lệ.

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-06-01 03:00:00.000000
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, None] = "d2e3f4a5b6c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_message", sa.Column("channel_id", sa.BigInteger(), nullable=True))
    op.add_column("agent_message", sa.Column("user_discord_id", sa.BigInteger(), nullable=True))
    # Tra "cuộc gần nhất của (kênh, người)" — lọc theo 3 cột rồi sắp theo id.
    op.create_index(
        "ix_agent_message_guild_channel_user",
        "agent_message",
        ["guild_id", "channel_id", "user_discord_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_message_guild_channel_user", table_name="agent_message")
    op.drop_column("agent_message", "user_discord_id")
    op.drop_column("agent_message", "channel_id")
