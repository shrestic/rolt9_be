"""Add XP decay config columns and user_xp.last_decay_at.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-29 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "guild_leveling_config",
        sa.Column(
            "xp_decay_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "guild_leveling_config",
        sa.Column(
            "xp_decay_percent",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("10"),
        ),
    )
    op.add_column(
        "guild_leveling_config",
        sa.Column(
            "xp_decay_inactivity_days",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("7"),
        ),
    )
    op.create_check_constraint(
        "ck_guild_leveling_config_decay_percent_range",
        "guild_leveling_config",
        "xp_decay_percent >= 1 AND xp_decay_percent <= 100",
    )
    op.create_check_constraint(
        "ck_guild_leveling_config_decay_days_positive",
        "guild_leveling_config",
        "xp_decay_inactivity_days >= 1",
    )
    op.add_column(
        "user_xp",
        sa.Column("last_decay_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_xp", "last_decay_at")
    op.drop_constraint(
        "ck_guild_leveling_config_decay_days_positive",
        "guild_leveling_config",
        type_="check",
    )
    op.drop_constraint(
        "ck_guild_leveling_config_decay_percent_range",
        "guild_leveling_config",
        type_="check",
    )
    op.drop_column("guild_leveling_config", "xp_decay_inactivity_days")
    op.drop_column("guild_leveling_config", "xp_decay_percent")
    op.drop_column("guild_leveling_config", "xp_decay_enabled")
