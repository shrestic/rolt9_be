"""Data access cho `guild_memory_doc` — doc markdown trí nhớ per-guild (OpenClaw-style).

append_note thêm 1 dòng bullet, bỏ trùng, và cắt bớt dòng CŨ nhất khi vượt cap (FIFO)
để doc luôn ≤ MEMORY_DOC_CAP (vì doc được nạp vào mọi prompt). Flush; commit ở boundary.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.guild_memory_doc import GuildMemoryDoc

MEMORY_DOC_CAP = 4000


def _cap(doc: str) -> str:
    """Giữ doc ≤ cap bằng cách bỏ dần dòng đầu (cũ nhất)."""
    while len(doc) > MEMORY_DOC_CAP and "\n" in doc:
        doc = doc.split("\n", 1)[1]
    return doc[-MEMORY_DOC_CAP:] if len(doc) > MEMORY_DOC_CAP else doc


class MemoryDocRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_doc(self, guild_id: uuid.UUID) -> str:
        r = await self.session.execute(
            select(GuildMemoryDoc.doc).where(GuildMemoryDoc.guild_id == guild_id)
        )
        return r.scalar_one_or_none() or ""

    async def _row(self, guild_id: uuid.UUID) -> GuildMemoryDoc:
        r = await self.session.execute(
            select(GuildMemoryDoc).where(GuildMemoryDoc.guild_id == guild_id)
        )
        row = r.scalar_one_or_none()
        if row is None:
            row = GuildMemoryDoc(guild_id=guild_id, doc="")
            self.session.add(row)
            await self.session.flush()
        return row

    async def set_doc(self, guild_id: uuid.UUID, doc: str) -> None:
        row = await self._row(guild_id)
        row.doc = _cap(doc)
        await self.session.flush()

    async def append_note(self, guild_id: uuid.UUID, note: str) -> None:
        note = note.strip()
        if not note:
            return
        row = await self._row(guild_id)
        line = f"- {note}"
        if line in (row.doc or ""):
            return  # đã có, bỏ trùng
        row.doc = _cap(f"{row.doc}\n{line}".strip() if row.doc else line)
        await self.session.flush()

    async def clear(self, guild_id: uuid.UUID) -> None:
        row = await self._row(guild_id)
        row.doc = ""
        await self.session.flush()
