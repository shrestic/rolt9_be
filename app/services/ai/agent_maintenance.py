"""Dọn rác `agent_message`: xoá các lượt hội thoại cũ hơn ngưỡng giữ (mặc định 90 ngày).

Lịch sử hội thoại Claw Agent tích lại mãi sẽ phình DB vô ích — chỉ vài lượt gần đây mới
được nạp vào prompt. Job nền chạy hằng ngày (AgentMaintenanceCog) gọi hàm thuần dưới đây.
Logic để riêng (không I/O Discord) cho dễ test; cog chỉ lo lịch.
"""

import logging
from datetime import datetime, timedelta

from app.db.session import session_scope
from app.repositories.agent_message import AgentMessageRepository

log = logging.getLogger(__name__)

AGENT_MESSAGE_RETENTION_DAYS = 90  # giữ lại 90 ngày gần nhất, cũ hơn thì xoá


async def purge_old_agent_messages(
    now: datetime, retention_days: int = AGENT_MESSAGE_RETENTION_DAYS
) -> int:
    """Xoá mọi lượt agent_message cũ hơn `retention_days` tính từ `now`. Trả số dòng đã xoá."""
    cutoff = now - timedelta(days=retention_days)
    async with session_scope() as session:
        deleted = await AgentMessageRepository(session).delete_older_than(cutoff)
    log.info("agent_message cleanup: xoá %d lượt cũ hơn %s", deleted, cutoff.date())
    return deleted
