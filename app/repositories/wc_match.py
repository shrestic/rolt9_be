"""Data access cho wc_match. upsert theo API match id; flush-only, commit ở boundary."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.wc_match import WCMatch

_FIELDS = (
    "competition",
    "stage",
    "matchday",
    "home_team",
    "home_code",
    "away_team",
    "away_code",
    "kickoff_at",
    "status",
    "home_score",
    "away_score",
    "ou_line",
    "handicap_team",
    "handicap_line",
)


class WCMatchRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert(self, data: dict) -> WCMatch:
        """Tạo/cập nhật trận theo `data['id']` (API id). Chỉ set field có trong data."""
        row = await self.session.get(WCMatch, data["id"])
        if row is None:
            row = WCMatch(id=data["id"])
            self.session.add(row)
        for f in _FIELDS:
            if f in data:
                setattr(row, f, data[f])
        await self.session.flush()
        return row

    async def finished_unsettled(self) -> list[WCMatch]:
        res = await self.session.execute(
            select(WCMatch).where(WCMatch.status == "finished", WCMatch.settled.is_(False))
        )
        return list(res.scalars().all())

    async def mark_settled(self, match_id: int) -> None:
        row = await self.session.get(WCMatch, match_id)
        if row is not None:
            row.settled = True
        await self.session.flush()

    async def get(self, match_id: int) -> WCMatch | None:
        return await self.session.get(WCMatch, match_id)
