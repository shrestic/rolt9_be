"""Companion: add `companion_last_post_at` so the cooldown survives a restart

The companion cooldown was previously kept in RAM (self.cooldown) -> every restart/deploy forgot it
-> the bot posted again immediately even though the admin set 45min. Store the last post time (UTC) in the DB
so the gate compares against the real clock and persists across restarts. Nullable -> old row = never posted yet.

Revision ID: bb22cc33dd44
Revises: aa11bb22cc33
Create Date: 2026-06-01 12:00:00.000000
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "bb22cc33dd44"
down_revision: Union[str, None] = "aa11bb22cc33"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "guild_ai_config",
        sa.Column("companion_last_post_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("guild_ai_config", "companion_last_post_at")
