"""Reminder: thêm cột `task` cho "smart reminder" (tới giờ thì TRA web + AI trả lời thật)

Khi user hẹn kiểu "5h chiều show giá vàng", reminder không chỉ echo chữ tĩnh mà phải
TRA CỨU sống (web_search) rồi AI trả lời lúc tới giờ. `task` = truy vấn cần tra; NULL =
reminder thường (chỉ nhắc `message`). Nullable -> mọi row cũ vẫn hợp lệ.

Revision ID: f8a9b0c1d2e3
Revises: f4a5b6c7d8e9
Create Date: 2026-06-01 10:00:00.000000
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "f8a9b0c1d2e3"
down_revision: Union[str, None] = "f4a5b6c7d8e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reminder", sa.Column("task", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("reminder", "task")
