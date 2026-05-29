"""Add streak columns to user_wallet and guild_currency_config.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-05-29 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # user_wallet: streak counters (server_default 0 backfills existing rows)
    op.add_column(
        "user_wallet",
        sa.Column("current_streak", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "user_wallet",
        sa.Column("longest_streak", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.create_check_constraint(
        "ck_user_wallet_streak_nonneg", "user_wallet", "current_streak >= 0"
    )
    op.create_check_constraint(
        "ck_user_wallet_longest_nonneg", "user_wallet", "longest_streak >= 0"
    )

    # guild_currency_config: streak knobs (defaults match the model)
    op.add_column(
        "guild_currency_config",
        sa.Column("streak_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "guild_currency_config",
        sa.Column(
            "streak_bonus_per_day", sa.Integer(), nullable=False, server_default=sa.text("10")
        ),
    )
    op.add_column(
        "guild_currency_config",
        sa.Column(
            "streak_bonus_cap", sa.Integer(), nullable=False, server_default=sa.text("500")
        ),
    )
    op.create_check_constraint(
        "ck_currency_streak_per_day_nonneg", "guild_currency_config", "streak_bonus_per_day >= 0"
    )
    op.create_check_constraint(
        "ck_currency_streak_cap_nonneg", "guild_currency_config", "streak_bonus_cap >= 0"
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_currency_streak_cap_nonneg", "guild_currency_config", type_="check"
    )
    op.drop_constraint(
        "ck_currency_streak_per_day_nonneg", "guild_currency_config", type_="check"
    )
    op.drop_column("guild_currency_config", "streak_bonus_cap")
    op.drop_column("guild_currency_config", "streak_bonus_per_day")
    op.drop_column("guild_currency_config", "streak_enabled")
    op.drop_constraint("ck_user_wallet_longest_nonneg", "user_wallet", type_="check")
    op.drop_constraint("ck_user_wallet_streak_nonneg", "user_wallet", type_="check")
    op.drop_column("user_wallet", "longest_streak")
    op.drop_column("user_wallet", "current_streak")
