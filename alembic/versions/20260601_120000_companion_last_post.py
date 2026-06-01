"""Companion: thêm `companion_last_post_at` để cooldown sống sót qua restart

Cooldown companion trước giữ trong RAM (self.cooldown) -> mỗi lần restart/deploy là quên
-> bot post lại ngay dù admin set 45'. Lưu thời điểm post cuối (UTC) vào DB để gate so
theo đồng hồ thực, bền qua restart. Nullable -> row cũ = chưa post lần nào.

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
