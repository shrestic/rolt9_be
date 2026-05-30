"""Add knowledge-base table: guild_kb_entry.

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-05-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, None] = "d0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "guild_kb_entry",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("guild_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("content", sa.String(length=2000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_guild_kb_entry_guild_id", "guild_kb_entry", ["guild_id"])


def downgrade() -> None:
    op.drop_index("ix_guild_kb_entry_guild_id", table_name="guild_kb_entry")
    op.drop_table("guild_kb_entry")
