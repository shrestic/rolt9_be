"""AI v2 BYO-key: guild_ai_config provider/model/api_key_enc/monthly_budget_usd, ai_usage cost_usd

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-05-31 03:00:00.000000
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "b4c5d6e7f8a9"
down_revision: Union[str, None] = "a3b4c5d6e7f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # guild_ai_config: thêm provider/model/api_key_enc/monthly_budget_usd.
    op.add_column(
        "guild_ai_config",
        sa.Column("provider", sa.String(length=32), nullable=False, server_default=""),
    )
    op.add_column(
        "guild_ai_config",
        sa.Column("model", sa.String(length=64), nullable=False, server_default=""),
    )
    op.add_column("guild_ai_config", sa.Column("api_key_enc", sa.LargeBinary(), nullable=True))
    op.add_column(
        "guild_ai_config",
        sa.Column(
            "monthly_budget_usd",
            sa.Numeric(precision=10, scale=4),
            nullable=False,
            server_default="5.0",
        ),
    )
    # Đổi check constraint token -> USD (drop cũ, drop cột cũ, tạo check mới).
    op.drop_constraint("ck_ai_budget_nonneg", "guild_ai_config", type_="check")
    op.drop_column("guild_ai_config", "monthly_token_budget")
    op.create_check_constraint("ck_ai_budget_nonneg", "guild_ai_config", "monthly_budget_usd >= 0")

    # ai_usage: thêm cost_usd + check.
    op.add_column(
        "ai_usage",
        sa.Column(
            "cost_usd",
            sa.Numeric(precision=12, scale=6),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_check_constraint("ck_ai_usage_cost_nonneg", "ai_usage", "cost_usd >= 0")


def downgrade() -> None:
    op.drop_constraint("ck_ai_usage_cost_nonneg", "ai_usage", type_="check")
    op.drop_column("ai_usage", "cost_usd")

    op.drop_constraint("ck_ai_budget_nonneg", "guild_ai_config", type_="check")
    op.add_column(
        "guild_ai_config",
        sa.Column(
            "monthly_token_budget",
            sa.Integer(),
            nullable=False,
            server_default="100000",
        ),
    )
    op.create_check_constraint(
        "ck_ai_budget_nonneg", "guild_ai_config", "monthly_token_budget >= 0"
    )
    op.drop_column("guild_ai_config", "monthly_budget_usd")
    op.drop_column("guild_ai_config", "api_key_enc")
    op.drop_column("guild_ai_config", "model")
    op.drop_column("guild_ai_config", "provider")
