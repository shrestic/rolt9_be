"""Data access for wc_prediction. upsert by (guild,match,user,bet_type) — editing a bet = update."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.wc_prediction import WCPrediction


class WCPredictionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert(self, guild_id, match_id: int, user_id: int, bet_type: str, pick: str) -> None:
        res = await self.session.execute(
            select(WCPrediction).where(
                WCPrediction.guild_id == guild_id,
                WCPrediction.match_id == match_id,
                WCPrediction.user_discord_id == user_id,
                WCPrediction.bet_type == bet_type,
            )
        )
        row = res.scalar_one_or_none()
        if row is None:
            self.session.add(
                WCPrediction(
                    guild_id=guild_id,
                    match_id=match_id,
                    user_discord_id=user_id,
                    bet_type=bet_type,
                    pick=pick,
                )
            )
        else:
            row.pick = pick
            row.points = None  # bet changed -> rescore later
        await self.session.flush()

    async def for_match(self, match_id: int) -> list[WCPrediction]:
        res = await self.session.execute(
            select(WCPrediction).where(WCPrediction.match_id == match_id)
        )
        return list(res.scalars().all())

    async def for_user_match(self, guild_id, match_id: int, user_id: int) -> list[WCPrediction]:
        res = await self.session.execute(
            select(WCPrediction).where(
                WCPrediction.guild_id == guild_id,
                WCPrediction.match_id == match_id,
                WCPrediction.user_discord_id == user_id,
            )
        )
        return list(res.scalars().all())

    async def set_points(self, prediction_id: int, points: int) -> None:
        row = await self.session.get(WCPrediction, prediction_id)
        if row is not None:
            row.points = points
        await self.session.flush()

    async def leaderboard(self, guild_id) -> list[tuple[int, int]]:
        """[(user_discord_id, total points)] descending — for the leaderboard (Phase 3)."""
        from sqlalchemy import func

        res = await self.session.execute(
            select(WCPrediction.user_discord_id, func.coalesce(func.sum(WCPrediction.points), 0))
            .where(WCPrediction.guild_id == guild_id)
            .group_by(WCPrediction.user_discord_id)
            .order_by(func.coalesce(func.sum(WCPrediction.points), 0).desc())
        )
        return [(uid, int(pts)) for uid, pts in res.all()]
