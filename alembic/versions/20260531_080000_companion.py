"""Companion AI: guild_ai_config companion_enabled/channel_id/cooldown_min

Revision ID: b0c1d2e3f4a5
Revises: a9b0c1d2e3f4
Create Date: 2026-05-31 08:00:00.000000
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "b0c1d2e3f4a5"
down_revision: Union[str, None] = "a9b0c1d2e3f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "guild_ai_config",
        sa.Column("companion_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "guild_ai_config", sa.Column("companion_channel_id", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "guild_ai_config",
        sa.Column("companion_cooldown_min", sa.Integer(), nullable=False, server_default="45"),
    )


def downgrade() -> None:
    op.drop_column("guild_ai_config", "companion_cooldown_min")
    op.drop_column("guild_ai_config", "companion_channel_id")
    op.drop_column("guild_ai_config", "companion_enabled")
