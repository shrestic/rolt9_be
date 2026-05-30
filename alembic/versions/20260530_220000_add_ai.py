"""Add AI tables: guild_ai_config, ai_usage.

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-05-30 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "guild_ai_config",
        sa.Column("guild_id", sa.UUID(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "monthly_token_budget", sa.Integer(), nullable=False, server_default=sa.text("100000")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("guild_id"),
        sa.CheckConstraint("monthly_token_budget >= 0", name="ck_ai_budget_nonneg"),
    )
    op.create_table(
        "ai_usage",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("guild_id", sa.UUID(), nullable=False),
        sa.Column("period_key", sa.String(length=7), nullable=False),
        sa.Column("tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("guild_id", "period_key", name="uq_ai_usage_period"),
        sa.CheckConstraint("tokens >= 0", name="ck_ai_usage_tokens_nonneg"),
    )
    op.create_index("ix_ai_usage_guild_id", "ai_usage", ["guild_id"])


def downgrade() -> None:
    op.drop_index("ix_ai_usage_guild_id", table_name="ai_usage")
    op.drop_table("ai_usage")
    op.drop_table("guild_ai_config")
