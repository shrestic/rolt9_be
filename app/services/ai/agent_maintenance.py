"""`agent_message` garbage collection: delete conversation turns older than the retention threshold (default 90 days).

Claw Agent conversation history piling up forever just bloats the DB for nothing — only a few
recent turns ever get loaded into the prompt. A daily background job (AgentMaintenanceCog) calls
the pure function below. The logic is kept separate (no Discord I/O) to make it easy to test; the
cog only handles scheduling.
"""

import logging
from datetime import datetime, timedelta

from app.db.session import session_scope
from app.repositories.agent_message import AgentMessageRepository

log = logging.getLogger(__name__)

AGENT_MESSAGE_RETENTION_DAYS = 90  # keep the most recent 90 days, delete anything older


async def purge_old_agent_messages(
    now: datetime, retention_days: int = AGENT_MESSAGE_RETENTION_DAYS
) -> int:
    """Delete every agent_message turn older than `retention_days` from `now`. Returns the row count deleted."""
    cutoff = now - timedelta(days=retention_days)
    async with session_scope() as session:
        deleted = await AgentMessageRepository(session).delete_older_than(cutoff)
    log.info("agent_message cleanup: deleted %d turns older than %s", deleted, cutoff.date())
    return deleted
