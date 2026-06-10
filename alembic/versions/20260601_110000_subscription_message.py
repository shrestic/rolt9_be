"""Subscription: add `message` (repeating personal reminder) + make `topic` nullable

Previously a subscription ONLY had the 'topic + web_search' mode -> "every day at 5:30 ping me to head home"
got stuffed by the model into topic='ping to head home' and then web search returned junk news. Add `message`:
if set, at the due time it just PINGS that line daily (no web_search). Each subscription is one of two: message
(static reminder) OR topic (news lookup). `topic` becomes nullable so a message-only row is valid.

Revision ID: aa11bb22cc33
Revises: f8a9b0c1d2e3
Create Date: 2026-06-01 11:00:00.000000
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "aa11bb22cc33"
down_revision: Union[str, None] = "f8a9b0c1d2e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("subscription", sa.Column("message", sa.Text(), nullable=True))
    op.alter_column("subscription", "topic", existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    op.alter_column("subscription", "topic", existing_type=sa.Text(), nullable=False)
    op.drop_column("subscription", "message")
