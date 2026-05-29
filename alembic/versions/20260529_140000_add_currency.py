"""Add server-currency tables: guild_currency_config, user_wallet.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-29 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "guild_currency_config",
        sa.Column("guild_id", sa.UUID(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("currency_name", sa.String(length=32), nullable=False, server_default="coins"),
        sa.Column("currency_emoji", sa.String(length=32), nullable=False, server_default="🪙"),
        sa.Column("earn_min", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("earn_max", sa.Integer(), nullable=False, server_default=sa.text("3")),
        sa.Column("daily_amount", sa.Integer(), nullable=False, server_default=sa.text("100")),
        sa.Column("allow_pay", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("guild_id"),
        sa.CheckConstraint("earn_min >= 0", name="ck_currency_earn_min_nonneg"),
        sa.CheckConstraint("earn_max >= 0", name="ck_currency_earn_max_nonneg"),
        sa.CheckConstraint("earn_min <= earn_max", name="ck_currency_earn_range"),
        sa.CheckConstraint("daily_amount >= 0", name="ck_currency_daily_nonneg"),
    )
    op.create_table(
        "user_wallet",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("guild_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("balance", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_daily_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("guild_id", "user_id", name="uq_user_wallet_guild_user"),
        sa.CheckConstraint("balance >= 0", name="ck_user_wallet_balance_nonneg"),
    )
    op.create_index("ix_user_wallet_guild_id", "user_wallet", ["guild_id"])
    op.create_index("ix_user_wallet_leaderboard", "user_wallet", ["guild_id", "balance"])


def downgrade() -> None:
    op.drop_index("ix_user_wallet_leaderboard", table_name="user_wallet")
    op.drop_index("ix_user_wallet_guild_id", table_name="user_wallet")
    op.drop_table("user_wallet")
    op.drop_table("guild_currency_config")
