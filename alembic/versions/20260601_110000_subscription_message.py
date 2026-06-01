"""Subscription: thêm `message` (nhắc cá nhân lặp lại) + cho `topic` nullable

Trước đây subscription CHỈ có chế độ 'topic + web_search' -> "mỗi ngày 5h30 hú tao đi về"
bị model nhét vào topic='hú đi về' rồi tra web ra tin rác. Thêm `message`: nếu set, tới giờ
chỉ PING câu đó hằng ngày (không web_search). Mỗi đăng ký là 1 trong 2: message (nhắc tĩnh)
HOẶC topic (tra tin). `topic` chuyển nullable để row chỉ-message hợp lệ.

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
