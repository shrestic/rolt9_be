"""Reminder: add `task` column for "smart reminder" (at the due time, SEARCH the web + AI gives a real answer)

When a user schedules something like "5pm show gold price", the reminder must not just echo
static text but do a live LOOKUP (web_search) and have the AI answer at the due time. `task` = the
query to look up; NULL = a normal reminder (only pings `message`). Nullable -> all old rows stay valid.

Revision ID: f8a9b0c1d2e3
Revises: f4a5b6c7d8e9
Create Date: 2026-06-01 10:00:00.000000
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "f8a9b0c1d2e3"
down_revision: Union[str, None] = "f4a5b6c7d8e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reminder", sa.Column("task", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("reminder", "task")
