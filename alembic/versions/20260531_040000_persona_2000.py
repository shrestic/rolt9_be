"""Widen guild_ai_config.persona 500 -> 2000 chars

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-05-31 04:00:00.000000
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "c5d6e7f8a9b0"
down_revision: Union[str, None] = "b4c5d6e7f8a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "guild_ai_config",
        "persona",
        existing_type=sa.String(length=500),
        type_=sa.String(length=2000),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "guild_ai_config",
        "persona",
        existing_type=sa.String(length=2000),
        type_=sa.String(length=500),
        existing_nullable=False,
    )
