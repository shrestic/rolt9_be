"""Data access for `guild_memory_doc` — per-guild SERVER MEMORY markdown doc (OpenClaw-style).

append_note adds one bullet line, deduplicates, and trims the OLDEST line when over cap (FIFO)
so the doc stays ≤ MEMORY_DOC_CAP (since the doc is loaded into every prompt). Flush; commit at boundary.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.guild_memory_doc import GuildMemoryDoc

MEMORY_DOC_CAP = 4000


def _cap(doc: str) -> str:
    """Keep the doc ≤ cap by dropping leading (oldest) lines one by one."""
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
            return  # already present, skip duplicate
        row.doc = _cap(f"{row.doc}\n{line}".strip() if row.doc else line)
        await self.session.flush()

    async def remove_notes(self, guild_id: uuid.UUID, query: str) -> list[str]:
        """Delete memory LINES MATCHING `query` (substring, case-insensitive).

        Returns the list of deleted line contents (empty = nothing matched) so we can report
        back to the user exactly what was forgotten. This is the 'forget' counterpart of append_note.
        """
        q = (query or "").strip().lower()
        if not q:
            return []
        row = await self._row(guild_id)
        kept: list[str] = []
        removed: list[str] = []
        for line in (row.doc or "").split("\n"):
            if line.strip() and q in line.lower():
                removed.append(line.lstrip("-").strip())
            else:
                kept.append(line)
        if removed:
            new_doc = "\n".join(kept).strip()
            if new_doc:
                row.doc = new_doc
            else:
                # Everything deleted -> DELETE the record too, don't leave an empty row in the DB.
                await self.session.delete(row)
            await self.session.flush()
        return removed

    async def clear(self, guild_id: uuid.UUID) -> None:
        """Wipe SERVER MEMORY = REMOVE the record entirely from the DB (don't leave an empty doc row). get_doc returns ''
        when there is no row; append_note recreates a new row when it needs to write."""
        r = await self.session.execute(
            select(GuildMemoryDoc).where(GuildMemoryDoc.guild_id == guild_id)
        )
        row = r.scalar_one_or_none()
        if row is not None:
            await self.session.delete(row)
            await self.session.flush()
