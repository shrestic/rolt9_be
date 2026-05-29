"""The `LevelingService` facade.

This is the **only** public entry point into the leveling pipeline. Every
caller — the HTTP API, the Discord listener, the slash command cogs —
talks to this class, never to the sub-services underneath.

Why a facade?

    1. **Stable surface.** We can re-shuffle internals (split a sub-service,
       merge two, swap LeaderboardService for an SQL view) without touching
       the listener or the endpoints. They only know about the facade.

    2. **Single composition root.** The constructor wires up four sub-services
       in one place. Sub-services don't import each other, so the dependency
       graph stays flat and easy to reason about.

    3. **Transaction boundary clarity.** Every public method on the facade
       represents one "unit of work" from the caller's point of view. The
       caller's `session_scope` / `get_db` commits once when the method
       returns successfully, and rolls back on exception.

Sub-services owned by composition:

    XpAwarder         → cooldown + random XP roll + per-user lock + write
    LevelRoleSync     → diff and apply level-reward roles
    LevelUpNotifier   → channel / DM / off announcement
    LeaderboardService → paginated, level-decorated leaderboard

Plus stateless helpers reached directly:

    content_filter.should_award → anti-spam gate
    xp_calculator               → XP↔level math, used for `get_rank` math
    rank_card_renderer types    → DTOs the cog passes to the renderer
"""

import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.colors import RankCardColors
from app.core.enums import BgType
from app.discord_io.client import DiscordClient
from app.repositories.guild import GuildRepository
from app.repositories.guild_rank_card_theme import GuildRankCardThemeRepository
from app.repositories.level_role_reward import LevelRoleRewardRepository
from app.repositories.leveling_config import GuildLevelingConfigRepository
from app.repositories.user_xp import UserXpRepository
from app.services.leveling.content_filter import FilterConfig, should_award
from app.services.leveling.leaderboard import LeaderboardPage, LeaderboardService
from app.services.leveling.level_role_sync import LevelRoleSync
from app.services.leveling.notification import LevelUpNotifier
from app.services.leveling.rank_card_renderer import RankCardData, RankCardTheme
from app.services.leveling.xp_awarder import AwardOutcome, XpAwarder
from app.services.leveling.xp_calculator import level_for_xp, total_xp_for_level, xp_to_next

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RankInfo:
    """A snapshot of a member's XP / level / rank position.

    Used as the return shape for `get_rank`, `set_member_xp`, and
    `reset_member`. Equivalent zero state (`rank=0, level=0, total_xp=0`,
    ...) means "this member has no XP row yet" — distinct from `None`
    which means "this guild isn't registered with the bot at all".

    Attributes:
        user_id: Discord snowflake of the member.
        rank: 1-indexed position in the guild leaderboard. 0 when the
            member has no XP row.
        level: Current level (derived from `total_xp`).
        total_xp: Cumulative XP in this guild.
        xp_into_level: XP earned *into* the current level — used as the
            numerator of the progress bar.
        xp_for_next_level: XP cost of the current level — used as the
            denominator of the progress bar.
    """

    user_id: int
    rank: int
    level: int
    total_xp: int
    xp_into_level: int
    xp_for_next_level: int


class LevelingService:
    """Orchestrates the leveling pipeline for one session / one request.

    Built fresh per request (HTTP) or per gateway event (bot). Holds:
        * The active SQLAlchemy `AsyncSession`.
        * The five repositories that read/write leveling tables.
        * Four composed sub-services that do the actual heavy lifting.

    Sub-services are owned by composition (not inheritance, not registry)
    so the dependency graph is explicit and any sub-service can be swapped
    by editing this one constructor.
    """

    def __init__(
        self,
        session: AsyncSession,
        discord_io: DiscordClient,
        guild_repo: GuildRepository,
        config_repo: GuildLevelingConfigRepository,
        xp_repo: UserXpRepository,
        reward_repo: LevelRoleRewardRepository,
        theme_repo: GuildRankCardThemeRepository,
    ):
        """Wire dependencies and instantiate the sub-services.

        Args:
            session: Active `AsyncSession`. Shared by every repo and by the
                `XpAwarder`. The session's caller — `get_db` for HTTP, the
                `session_scope` async-with for the bot — owns the commit.
            discord_io: The bot's `BotDiscordClient`. Used directly by the
                notifier and role-sync sub-services.
            guild_repo: Resolves Discord snowflakes → internal UUIDs.
            config_repo: Reads `guild_leveling_config` (the on/off + tuning
                row).
            xp_repo: Reads / writes `user_xp` rows.
            reward_repo: Reads / writes `level_role_reward` rows.
            theme_repo: Reads `guild_rank_card_theme` for the rank card.
        """
        self.session = session
        self.discord_io = discord_io
        self.guild_repo = guild_repo
        self.config_repo = config_repo
        self.xp_repo = xp_repo
        self.reward_repo = reward_repo
        self.theme_repo = theme_repo

        # Sub-services. Each one only depends on what it strictly needs;
        # we don't pass the whole `self` around, on purpose.
        self._awarder = XpAwarder(session=session, xp_repo=xp_repo)
        self._role_sync = LevelRoleSync(reward_repo=reward_repo, discord_io=discord_io)
        self._notifier = LevelUpNotifier(discord_io=discord_io)
        self._leaderboard = LeaderboardService(xp_repo=xp_repo)

    async def process_message(
        self,
        *,
        guild_discord_id: int,
        user_id: int,
        username: str,
        content: str,
        channel_id: int | None = None,
        member_role_ids: list[int] | None = None,
    ) -> AwardOutcome | None:
        """Process one chat message: maybe award XP, maybe trigger level-up.

        This is the **hot path** — runs for every Discord message that
        passes the bot-side cheap rejection. We walk a ladder of gates,
        cheapest first; the first failure returns `None`.

        Gate order:
            1. Is the guild registered with the bot?
            2. Is leveling enabled for the guild?
            3. Is the source channel in `ignored_channel_ids`?
            4. Does the member hold any role in `ignored_role_ids`?
            5. Does the message *content* pass the anti-spam filter?
            6. Does the **cooldown** gate (inside XpAwarder) allow it?

        If all gates pass, `XpAwarder.award(...)` writes the XP and returns
        an `AwardOutcome`. We then check `new_level > old_level` — if true,
        we run two side effects in order:
            * `LevelRoleSync.apply(...)` to grant/strip reward roles.
            * `LevelUpNotifier.send(...)` to post the announcement.

        Both side effects are inside the same DB transaction as the XP
        write. If either raises, the transaction rolls back and the XP is
        un-written — easier to retry than to debug half-applied state.

        Args:
            guild_discord_id: Discord snowflake of the guild the message
                arrived in.
            user_id: Discord snowflake of the author.
            username: Display name used in the level-up announcement.
                We accept the string directly so we don't have to fetch the
                member again on the level-up path.
            content: Raw message text. Trimmed by the filter, not here.
            channel_id: Discord snowflake of the channel. Optional because
                some test paths skip it; in production the listener always
                passes it so the ignored-channels gate works.
            member_role_ids: Member's current role snowflakes. Optional
                for the same reason; without it the ignored-roles gate is
                a no-op.

        Returns:
            `AwardOutcome` on success. `None` when *any* gate rejected the
            message — callers don't get to know which gate; that's a
            deliberate information-hiding choice.

        Example:
            >>> outcome = await service.process_message(
            ...     guild_discord_id=999, user_id=42, username="Alice",
            ...     content="hello team", channel_id=123, member_role_ids=[]
            ... )
            >>> outcome.new_level if outcome else None
            5
        """
        # Gate 1: is the guild registered?
        guild = await self.guild_repo.get_by_discord_id(guild_discord_id)
        if guild is None:
            return None

        # Gate 2: is leveling enabled? `cfg is None` means the row never
        # got created (admin never opened the page); treat the same as off.
        cfg = await self.config_repo.get(guild.id)
        if cfg is None or not cfg.enabled:
            return None

        # Gate 3: channel ignore list. The set comprehension coerces both
        # sides to int because JSON columns sometimes round-trip strings.
        if channel_id is not None and int(channel_id) in {
            int(x) for x in (cfg.ignored_channel_ids or [])
        }:
            return None

        # Gate 4: role ignore list. Reject if the member shares any role
        # with the configured set. Empty `member_role_ids` skips the check.
        if member_role_ids:
            if {int(x) for x in (cfg.ignored_role_ids or [])} & {int(r) for r in member_role_ids}:
                return None

        # Gate 5: content filter. We build the `FilterConfig` from the
        # leveling-config row each time — small enough to not bother
        # caching, and keeps the filter module independent of the ORM.
        fcfg = FilterConfig(
            min_message_length=cfg.min_message_length,
            ignore_emoji_only=cfg.ignore_emoji_only,
            ignore_link_only=cfg.ignore_link_only,
        )
        if not should_award(content, fcfg):
            return None

        # Gate 6 lives inside XpAwarder.award. It also does the actual
        # write and returns the outcome we hand back to the caller.
        outcome = await self._awarder.award(guild_id=guild.id, user_id=user_id, config=cfg)
        if outcome is None:
            return None

        # Level-up side effects. Only fired when the award crossed a
        # threshold; same-level awards skip both calls to keep the chat
        # path lean.
        if outcome.new_level > outcome.old_level:
            await self._role_sync.apply(
                guild_id=guild.id,
                guild_discord_id=guild_discord_id,
                user_id=user_id,
                new_level=outcome.new_level,
                mode=cfg.level_role_mode,
            )
            await self._notifier.send(
                config=cfg, user_id=user_id, username=username, new_level=outcome.new_level
            )
        return outcome

    async def get_rank(self, *, guild_discord_id: int, user_id: int) -> RankInfo | None:
        """Look up a member's current rank / level / XP figures.

        Used by:
            * `/rank` (cog) — wraps the result in a `RankCardData` and
              renders the PNG.
            * `GET /leveling/members/{user_id}` — returns `MemberXpOut`.

        Distinguishes "guild not registered" (returns `None`) from "guild
        registered but member has no XP yet" (returns `RankInfo` with
        zero values across the board). That distinction is what lets the
        HTTP layer answer "I never sent a tracked message" with a clean
        zero state rather than a 404.

        Args:
            guild_discord_id: Discord snowflake of the guild.
            user_id: Discord snowflake of the member.

        Returns:
            `RankInfo` for any registered guild — zero-valued when the
            member has no `user_xp` row yet. `None` when the guild itself
            isn't in the `guilds` table (bot was never invited / was
            kicked).

        Example:
            >>> info = await service.get_rank(guild_discord_id=999, user_id=42)
            >>> info.level, info.total_xp
            (5, 720)
        """
        guild = await self.guild_repo.get_by_discord_id(guild_discord_id)
        if guild is None:
            return None

        # `row` may be None (no XP entry yet) — fall back to zero so we
        # can still build a meaningful `RankInfo`.
        row = await self.xp_repo.get(guild.id, user_id)
        total_xp = row.total_xp if row else 0

        # Three derived figures used by the renderer: current level,
        # XP into current level, XP for the next level.
        level = level_for_xp(total_xp)
        threshold = total_xp_for_level(level)
        xp_into_level = total_xp - threshold
        xp_for_next_level = xp_to_next(level)

        # `rank_of` returns `None` when there's no row; that becomes a
        # display rank of 0 ("unranked").
        rank = await self.xp_repo.rank_of(guild.id, user_id)

        return RankInfo(
            user_id=user_id,
            rank=rank or 0,
            level=level,
            total_xp=total_xp,
            xp_into_level=xp_into_level,
            xp_for_next_level=xp_for_next_level,
        )

    async def set_member_xp(
        self, *, guild_discord_id: int, user_id: int, total_xp: int
    ) -> RankInfo | None:
        """Admin override — set XP to an exact value and sync reward roles.

        Used by `PATCH /leveling/members/{user_id}` for moderation /
        balancing actions ("this user lost 10 levels worth of XP to a bug,
        give them back X"). After the write, we recompute the new level
        and run `LevelRoleSync` so the member's role state matches.

        Why role sync is mandatory here: silently bumping or lowering XP
        without adjusting reward roles would leave the member holding (or
        missing) roles that don't match their level. That mismatch is
        confusing and hard to debug later.

        Args:
            guild_discord_id: Discord snowflake of the guild.
            user_id: Discord snowflake of the member.
            total_xp: Absolute XP to set. The endpoint validates `>= 0`
                via Pydantic; we don't re-validate here.

        Returns:
            Updated `RankInfo`. `None` only when the guild isn't registered.
        """
        guild = await self.guild_repo.get_by_discord_id(guild_discord_id)
        if guild is None:
            return None

        # Config may be None if the admin never opened the settings page.
        # We still write the XP, but skip role sync (no role rewards
        # exist either, so it'd be a no-op).
        cfg = await self.config_repo.get(guild.id)

        # Ensure the row exists, then overwrite the XP. `set_xp` with no
        # `last_xp_at` keeps the cooldown timestamp untouched — admin
        # overrides shouldn't artificially extend the cooldown window.
        await self.xp_repo.get_or_create(guild.id, user_id)
        await self.xp_repo.set_xp(guild.id, user_id=user_id, total_xp=total_xp)

        if cfg is not None:
            # Sync to the new level. `apply` is idempotent; if the level
            # didn't actually change, the diff is empty and Discord isn't
            # touched.
            new_level = level_for_xp(total_xp)
            await self._role_sync.apply(
                guild_id=guild.id,
                guild_discord_id=guild_discord_id,
                user_id=user_id,
                new_level=new_level,
                mode=cfg.level_role_mode,
            )

        # Re-read so the response reflects the rank-of position (which
        # depends on every other member's XP, not just this row).
        return await self.get_rank(guild_discord_id=guild_discord_id, user_id=user_id)

    async def reset_member(self, *, guild_discord_id: int, user_id: int) -> RankInfo | None:
        """Admin reset — wipe the XP row and strip every level-granted role.

        Used by `DELETE /leveling/members/{user_id}`. Idempotent: safe to
        call when the member has no row yet (the delete is a no-op) and
        safe to call repeatedly.

        We deliberately call `LevelRoleSync.apply(new_level=0)` even though
        the member's level naturally becomes 0 after the delete. The
        call is what guarantees role stripping: with `new_level=0`,
        `target_role_ids` is empty, so the diff removes every managed
        role the member currently holds. That happens even when the
        member is offline.

        Args:
            guild_discord_id: Discord snowflake of the guild.
            user_id: Discord snowflake of the member to reset.

        Returns:
            A zero-state `RankInfo` (`rank=0, level=0, total_xp=0` …).
            `None` only when the guild isn't registered.
        """
        guild = await self.guild_repo.get_by_discord_id(guild_discord_id)
        if guild is None:
            return None

        cfg = await self.config_repo.get(guild.id)

        # Drop the row. Safe even if there isn't one.
        await self.xp_repo.delete(guild.id, user_id)

        if cfg is not None:
            # new_level=0 → target_role_ids is empty → every managed role
            # the member currently has gets stripped. See LevelRoleSync.
            await self._role_sync.apply(
                guild_id=guild.id,
                guild_discord_id=guild_discord_id,
                user_id=user_id,
                new_level=0,
                mode=cfg.level_role_mode,
            )

        # Re-read for a clean zero RankInfo.
        return await self.get_rank(guild_discord_id=guild_discord_id, user_id=user_id)

    async def get_theme(self, *, guild_discord_id: int, user_id: int) -> RankCardTheme:
        """Resolve the rank card theme for one (guild, user).

        Fallback chain:
            1. (Phase 3.1.5, not yet implemented) per-user theme override.
            2. Guild default from `guild_rank_card_theme`.
            3. Bot-wide hardcoded `_DEFAULT_THEME` (dark gradient, gold accent).

        The `user_id` parameter is kept on the signature so that when the
        per-user lookup lands, callers don't need to be updated.

        Args:
            guild_discord_id: Discord snowflake of the guild.
            user_id: Discord snowflake of the member. Currently unused but
                kept for API stability.

        Returns:
            A `RankCardTheme` — never `None`. We always have *some* theme
            because the bot-wide default is always available.
        """
        guild = await self.guild_repo.get_by_discord_id(guild_discord_id)
        if guild is None:
            # Unregistered guild → bot default. (We could 404 instead, but
            # the renderer is downstream of the cog's guild check, so this
            # branch should be unreachable in practice.)
            return _DEFAULT_THEME

        t = await self.theme_repo.get(guild.id)
        if t is None:
            # Guild registered but never customised → bot default.
            return _DEFAULT_THEME

        # Guild-default row exists; lift its colours into the dataclass.
        return RankCardTheme(
            bg_type=t.bg_type,
            bg_color_1=t.bg_color_1,
            bg_color_2=t.bg_color_2,
            accent_color=t.accent_color,
            text_color=t.text_color,
        )

    async def build_rank_card_data(
        self, *, guild_discord_id: int, user_id: int, username: str
    ) -> RankCardData | None:
        """Shape DB state into the `RankCardData` the renderer wants.

        The renderer is intentionally ORM-agnostic — it takes a plain
        dataclass. This method is the bridge: it calls `get_rank` to
        pull the figures, then constructs the dataclass with the caller's
        `username` (the member's display name, which the renderer doesn't
        know how to fetch on its own).

        Args:
            guild_discord_id: Discord snowflake of the guild.
            user_id: Discord snowflake of the member.
            username: Display name to print on the card.

        Returns:
            A `RankCardData` ready to pass to `RankCardRenderer.render_async`.
            `None` when the guild isn't registered (i.e. `get_rank` returned
            `None`).
        """
        info = await self.get_rank(guild_discord_id=guild_discord_id, user_id=user_id)
        if info is None:
            return None
        return RankCardData(
            username=username,
            rank=info.rank,
            level=info.level,
            total_xp=info.total_xp,
            xp_into_level=info.xp_into_level,
            xp_for_next_level=info.xp_for_next_level,
        )

    async def leaderboard(self, *, guild_id, limit: int = 20, offset: int = 0) -> LeaderboardPage:
        """Return one page of the guild leaderboard.

        Thin pass-through to `LeaderboardService.top` — exists on the
        facade so callers depend on a single service rather than
        `LeaderboardService` directly. That keeps the public surface
        consistent.

        Args:
            guild_id: Internal UUID of the guild (not the Discord
                snowflake). Resolve via `GuildRepository.get_by_discord_id`
                in the caller if needed.
            limit: Page size. HTTP schema caps at 100; Discord slash uses 10.
            offset: How many rows to skip. `(page - 1) * page_size`.

        Returns:
            A `LeaderboardPage` with `items` (ranked, descending XP) and
            `total` (full row count for pagination UI).
        """
        return await self._leaderboard.top(guild_id, limit=limit, offset=offset)


# Bot-wide default rank-card palette. The colours are picked to look OK
# on most servers without customisation: dark blue-purple background,
# amber accent. Defined as a module-level constant so we don't allocate
# a new dataclass on every fallback.
_DEFAULT_THEME = RankCardTheme(
    bg_type=BgType.GRADIENT,
    bg_color_1=RankCardColors.DEFAULT_BG_PRIMARY,
    bg_color_2=RankCardColors.DEFAULT_BG_SECONDARY,
    accent_color=RankCardColors.DEFAULT_ACCENT,
    text_color=RankCardColors.DEFAULT_TEXT,
)
