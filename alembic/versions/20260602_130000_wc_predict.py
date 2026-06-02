"""WC Predict: wc_match, wc_prediction, guild_wc_config, wc_shame

Revision ID: c0ffee0wc001
Revises: bb22cc33dd44
Create Date: 2026-06-02 13:00:00.000000
"""

from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "c0ffee0wc001"
down_revision: Union[str, None] = "bb22cc33dd44"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wc_match",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("competition", sa.String(16), nullable=False, server_default="WC"),
        sa.Column("stage", sa.String(40), nullable=True),
        sa.Column("matchday", sa.Integer(), nullable=True),
        sa.Column("home_team", sa.String(64), nullable=False),
        sa.Column("home_code", sa.String(8), nullable=True),
        sa.Column("away_team", sa.String(64), nullable=False),
        sa.Column("away_code", sa.String(8), nullable=True),
        sa.Column("kickoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="scheduled"),
        sa.Column("home_score", sa.Integer(), nullable=True),
        sa.Column("away_score", sa.Integer(), nullable=True),
        sa.Column("ou_line", sa.Float(), nullable=False, server_default="2.5"),
        sa.Column("handicap_team", sa.String(8), nullable=True),
        sa.Column("handicap_line", sa.Float(), nullable=True),
        sa.Column("settled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_wc_match_kickoff_at", "wc_match", ["kickoff_at"])
    op.create_table(
        "guild_wc_config",
        sa.Column(
            "guild_id",
            UUID(as_uuid=True),
            sa.ForeignKey("guilds.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("channel_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "shame_nick_prefix", sa.String(40), nullable=False, server_default="🤡 Non Tay — "
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "wc_prediction",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "guild_id",
            UUID(as_uuid=True),
            sa.ForeignKey("guilds.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "match_id",
            sa.BigInteger(),
            sa.ForeignKey("wc_match.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_discord_id", sa.BigInteger(), nullable=False),
        sa.Column("bet_type", sa.String(8), nullable=False),
        sa.Column("pick", sa.String(32), nullable=False),
        sa.Column("points", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "guild_id", "match_id", "user_discord_id", "bet_type", name="uq_wc_prediction"
        ),
    )
    op.create_index("ix_wc_prediction_guild_id", "wc_prediction", ["guild_id"])
    op.create_index("ix_wc_prediction_match_id", "wc_prediction", ["match_id"])
    op.create_table(
        "wc_shame",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "guild_id",
            UUID(as_uuid=True),
            sa.ForeignKey("guilds.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_discord_id", sa.BigInteger(), nullable=False),
        sa.Column("original_nick", sa.String(64), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("guild_id", "user_discord_id", name="uq_wc_shame"),
    )
    op.create_index("ix_wc_shame_guild_id", "wc_shame", ["guild_id"])


def downgrade() -> None:
    op.drop_table("wc_shame")
    op.drop_table("wc_prediction")
    op.drop_table("guild_wc_config")
    op.drop_index("ix_wc_match_kickoff_at", table_name="wc_match")
    op.drop_table("wc_match")
