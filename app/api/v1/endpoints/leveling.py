"""HTTP endpoints for the leveling feature.

Every route here is mounted under `/api/v1/guilds/{guild_id}/leveling/...`
and gated by `require_managed_guild` (dashboard auth + the user must
have `manage_guild` on the target server + the bot must actually be in
the server). The dependency injects a `Guild` ORM row, so handlers can
use the internal UUID directly.

Three flavours of route live in this module:

    1. **Settings** (`/settings`)  — read/write the per-guild on/off and
       tuning row. The PUT handler also pokes the bot's in-process
       `LevelingConfigCache` so changes propagate within milliseconds
       instead of waiting for the cache's 45-second TTL.

    2. **Member XP** (`/members/{user_id}`)  — read one member's rank,
       admin-override their XP, or reset them to zero. All three go
       through `LevelingService` so role-sync side effects fire from
       admin actions just like they do for chat-driven level-ups.

    3. **Rewards & theme** (`/rewards`, `/rank-card-theme`)  — small
       CRUD endpoints that hit the repos directly because there's no
       business logic between the wire and the DB.

Snowflakes (user IDs, channel IDs, role IDs) are **strings on the wire**
in both directions. JSON numbers lose precision past 2^53; client code
treats them as opaque strings. We coerce to int once, at the database
boundary inside the handler, and stringify on the way back out.

Transaction model: every handler runs inside `get_db`'s `async with`
block. The session commits when the handler returns successfully and
rolls back on any exception. Repos in this module **never commit on
their own**; see `app/db/session.py` for the boundary code.
"""

from fastapi import APIRouter, Depends, Path, Query, Request

from app.dependencies.guild import require_managed_guild
from app.dependencies.services import (
    get_guild_rank_card_theme_repository,
    get_level_role_reward_repository,
    get_leveling_config_repository,
    get_leveling_service,
)
from app.exceptions.http_exceptions import NotFoundError
from app.models.guild import Guild
from app.repositories.guild_rank_card_theme import GuildRankCardThemeRepository
from app.repositories.level_role_reward import LevelRoleRewardRepository
from app.repositories.leveling_config import GuildLevelingConfigRepository
from app.schemas.leveling import (
    LeaderboardEntryOut,
    LeaderboardPageOut,
    LevelingSettings,
    LevelRewardCreate,
    LevelRewardOut,
    MemberXpOut,
    MemberXpUpdate,
    RankCardThemeIO,
)
from app.services.leveling import LevelingService
from app.services.leveling.xp_calculator import xp_to_next

router = APIRouter()

# Discord snowflakes are 64-bit ints rendered as decimal strings (currently
# 17-19 digits in production). We validate "all digits" — strict enough to
# reject "abc" / "1.5" / "-1" / "" with a clean 422, loose enough that test
# fixtures using short IDs ("42") still pass. The narrower 17-20 form would
# block tests without buying real safety, since `int("9" * 50)` is a valid
# Python int regardless and any overflow surfaces at the DB BigInteger
# boundary (also a 4xx).
_SNOWFLAKE_REGEX = r"^\d+$"


def _invalidate_cache(request: Request, guild_discord_id: int) -> None:
    """Drop this guild's entry from the bot's in-process leveling cache.

    `LevelingConfigCache` (in `app/bot/cache/leveling_config_cache.py`)
    caches the full leveling-config row keyed by Discord snowflake. Its
    TTL is 45 seconds, which is short enough for misconfigured guilds to
    self-correct over time — but not short enough that an admin pressing
    Save wants to wait. This helper invalidates the key so the *next*
    chat message picks up the new config without delay.

    Why we reach into `app.state.bot` rather than taking the cache as a
    DI dependency: the bot is a process-lifetime singleton owned by
    FastAPI's lifespan, not the request scope, so DI factories don't
    have a clean way to surface it. The `getattr` guards make this code
    safe in tests where the bot isn't started.

    Args:
        request: The current FastAPI request. We reach into
            `request.app.state.bot` to find the cache.
        guild_discord_id: Discord snowflake of the guild whose entry to
            invalidate. Internal UUIDs aren't used by the cache.
    """
    bot = getattr(request.app.state, "bot", None)
    cache = getattr(bot, "leveling_config_cache", None) if bot else None
    if cache is not None:
        cache.invalidate(guild_discord_id)


def _settings_out(cfg) -> LevelingSettings:
    """Convert a `GuildLevelingConfig` ORM row to the `LevelingSettings` DTO.

    Two things this function takes responsibility for:

        1. **Snowflake stringification.** All ID-like fields go out as
           strings, not numbers. Channel and role IDs come back as
           `["111", "222"]`; `notification_channel_id` is either a
           string or `null`.

        2. **NULL safety on JSON columns.** `ignored_channel_ids` and
           `ignored_role_ids` are JSON columns; defensive `or []` handles
           pre-defaults rows from before we set `server_default='[]'`.

    Used by both GET and PUT to keep response shape identical.

    Args:
        cfg: A `GuildLevelingConfig` row. Type-hinted as `Any` (just `cfg`)
            because importing the model here would couple the endpoint
            module to SQLAlchemy types unnecessarily.

    Returns:
        A fully-populated `LevelingSettings` Pydantic model.
    """
    return LevelingSettings(
        enabled=cfg.enabled,
        xp_min=cfg.xp_min,
        xp_max=cfg.xp_max,
        cooldown_seconds=cfg.cooldown_seconds,
        min_message_length=cfg.min_message_length,
        ignore_emoji_only=cfg.ignore_emoji_only,
        ignore_link_only=cfg.ignore_link_only,
        ignored_channel_ids=[str(x) for x in (cfg.ignored_channel_ids or [])],
        ignored_role_ids=[str(x) for x in (cfg.ignored_role_ids or [])],
        notification_mode=cfg.notification_mode,
        notification_channel_id=(
            str(cfg.notification_channel_id) if cfg.notification_channel_id is not None else None
        ),
        level_role_mode=cfg.level_role_mode,
        xp_decay_enabled=cfg.xp_decay_enabled,
        xp_decay_percent=cfg.xp_decay_percent,
        xp_decay_inactivity_days=cfg.xp_decay_inactivity_days,
    )


# ─── Settings ──────────────────────────────────────────────────────────


@router.get("/{guild_id}/leveling/settings", response_model=LevelingSettings)
async def get_settings(
    guild: Guild = Depends(require_managed_guild),
    repo: GuildLevelingConfigRepository = Depends(get_leveling_config_repository),
):
    """Return the leveling config for `guild_id`, creating defaults on first call.

    `repo.get_or_create` is what makes this a "no 404 ever" endpoint: the
    first time an admin opens the leveling page for a fresh guild, we
    silently create the row with sensible defaults (off, xp_min=15,
    xp_max=25, 60s cooldown, etc.). The admin sees defaults rather than
    a "set up leveling first" empty state.
    """
    cfg = await repo.get_or_create(guild.id)
    return _settings_out(cfg)


@router.put("/{guild_id}/leveling/settings", response_model=LevelingSettings)
async def update_settings(
    payload: LevelingSettings,
    request: Request,
    guild: Guild = Depends(require_managed_guild),
    repo: GuildLevelingConfigRepository = Depends(get_leveling_config_repository),
):
    """Upsert the leveling config and invalidate the bot's in-process cache.

    Sequence:

        1. Take the Pydantic-validated payload (the schema's
           `@model_validator` already enforced `xp_min <= xp_max` and the
           "channel mode needs channel_id when enabled" rule).
        2. Coerce ID-shaped fields from string back to int for the DB.
           This is the inverse of `_settings_out`'s stringification.
        3. `repo.upsert(...)` writes the row (flush only; commit happens
           when the handler returns via `get_db`).
        4. `_invalidate_cache(...)` drops the bot's cached config so the
           next chat message picks up the change immediately.
        5. Return the *upserted* row via `_settings_out` — round-tripping
           the payload would skip any DB-applied defaults.

    Important ordering note: we invalidate the cache **after** the
    upsert. If the upsert fails, `get_db` rolls back the transaction and
    the cache hasn't been touched yet — no drift. If the upsert succeeds
    but the cache invalidation fails (extremely unlikely; in-memory
    dict.pop), the worst case is a 45-second TTL until the next refresh.
    """
    data = payload.model_dump()

    # Coerce ID fields back to int. The schema serialises them as strings
    # to dodge JSON number precision; the DB column is BigInteger.
    data["ignored_channel_ids"] = [int(x) for x in data["ignored_channel_ids"]]
    data["ignored_role_ids"] = [int(x) for x in data["ignored_role_ids"]]
    data["notification_channel_id"] = (
        int(data["notification_channel_id"])
        if data["notification_channel_id"] is not None
        else None
    )

    cfg = await repo.upsert(guild.id, data)
    _invalidate_cache(request, guild.discord_id)
    return _settings_out(cfg)


# ─── Leaderboard ───────────────────────────────────────────────────────


@router.get("/{guild_id}/leveling/leaderboard", response_model=LeaderboardPageOut)
async def get_leaderboard(
    guild: Guild = Depends(require_managed_guild),
    # `le=10_000` caps deep pagination — with page_size=100 that's still
    # 1M rows of reach, far past any realistic dashboard scroll. Without
    # the cap, ?page=999999999 turns into a billion-row OFFSET that PG
    # happily attempts before returning empty.
    page: int = Query(default=1, ge=1, le=10_000),
    page_size: int = Query(default=20, ge=1, le=100),
    service: LevelingService = Depends(get_leveling_service),
):
    """Return a paginated, level-decorated leaderboard for the guild.

    Pagination uses 1-indexed `page` (so links can be human-readable) and
    `page_size` capped at 100 (so a runaway client can't ask for a
    million rows at once). The underlying service uses `offset` math
    internally.

    Members appear in DESC XP order with stable `user_id ASC` tiebreak.
    The full `total` count is returned in the envelope so the UI can
    render a proper page indicator without a second round-trip.

    Each entry's `user_id` is stringified for the same JSON-precision
    reason described in the module docstring.
    """
    data = await service.leaderboard(
        guild_id=guild.id, limit=page_size, offset=(page - 1) * page_size
    )
    return LeaderboardPageOut(
        items=[
            LeaderboardEntryOut(
                rank=e.rank, user_id=str(e.user_id), total_xp=e.total_xp, level=e.level
            )
            for e in data.items
        ],
        total=data.total,
        page=page,
        page_size=page_size,
    )


# ─── Member XP ─────────────────────────────────────────────────────────


def _member_out_from_rank(user_id: int, info) -> MemberXpOut:
    """Convert a `RankInfo` (or `None`) into the `MemberXpOut` DTO.

    Two cases:

        - `info is None` → the guild isn't registered with the bot
          (`get_rank` returns `None` in that case). We still return a
          200 with zero values rather than 404, so dashboard UIs render
          "no XP yet" cleanly. The required `xp_for_next_level` is
          computed via `xp_to_next(0)` so the field isn't bogus.

        - `info` is a `RankInfo` → straight 1-to-1 copy. We stringify
          `user_id` for JSON number-precision reasons.

    Args:
        user_id: The user ID the caller asked about. Used as the
            response `user_id` for the `None` case.
        info: A `RankInfo` from `LevelingService` or `None`.

    Returns:
        A `MemberXpOut` Pydantic model.
    """
    if info is None:
        return MemberXpOut(
            user_id=str(user_id),
            rank=0,
            level=0,
            total_xp=0,
            xp_into_level=0,
            # The schema declares this field required; even at level 0
            # we have a valid `xp_to_next(0) == 100`.
            xp_for_next_level=xp_to_next(0),
        )
    return MemberXpOut(
        user_id=str(info.user_id),
        rank=info.rank,
        level=info.level,
        total_xp=info.total_xp,
        xp_into_level=info.xp_into_level,
        xp_for_next_level=info.xp_for_next_level,
    )


@router.get("/{guild_id}/leveling/members/{user_id}", response_model=MemberXpOut)
async def get_member(
    user_id: str = Path(..., pattern=_SNOWFLAKE_REGEX),
    guild: Guild = Depends(require_managed_guild),
    service: LevelingService = Depends(get_leveling_service),
):
    """Look up one member's rank / level / XP figures.

    Path param `user_id` is typed `str` because Discord snowflakes
    overflow JS `Number.MAX_SAFE_INTEGER`. We coerce to int once,
    inside the handler, before calling the service.

    Routes through `LevelingService.get_rank` rather than the repo
    directly so the same math (level, xp_into_level, xp_for_next_level)
    that the cog uses is what the dashboard sees.
    """
    uid = int(user_id)
    info = await service.get_rank(guild_discord_id=guild.discord_id, user_id=uid)
    return _member_out_from_rank(uid, info)


@router.patch("/{guild_id}/leveling/members/{user_id}", response_model=MemberXpOut)
async def update_member(
    payload: MemberXpUpdate,
    user_id: str = Path(..., pattern=_SNOWFLAKE_REGEX),
    guild: Guild = Depends(require_managed_guild),
    service: LevelingService = Depends(get_leveling_service),
):
    """Admin XP override. Sets the member's `total_xp` and re-syncs roles.

    The role sync is what makes this safe to call: if an admin drops a
    user from 5000 XP to 100, the reward roles they earned at higher
    levels are stripped. If they bump someone up, the missing reward
    roles are granted. See `LevelingService.set_member_xp` for the
    detailed flow.

    The response reflects the **post-write** state, including their new
    rank position (which may have shifted significantly relative to
    other members).
    """
    uid = int(user_id)
    info = await service.set_member_xp(
        guild_discord_id=guild.discord_id, user_id=uid, total_xp=payload.total_xp
    )
    return _member_out_from_rank(uid, info)


@router.delete("/{guild_id}/leveling/members/{user_id}", response_model=MemberXpOut)
async def reset_member(
    user_id: str = Path(..., pattern=_SNOWFLAKE_REGEX),
    guild: Guild = Depends(require_managed_guild),
    service: LevelingService = Depends(get_leveling_service),
):
    """Wipe a member's XP row and strip every level-granted role.

    The response is a fresh `RankInfo` (rank=0, level=0, total_xp=0,
    xp_into_level=0) for the member — confirming the reset took effect.
    Idempotent: calling DELETE twice on the same member is fine.
    """
    uid = int(user_id)
    info = await service.reset_member(guild_discord_id=guild.discord_id, user_id=uid)
    return _member_out_from_rank(uid, info)


# ─── Rewards ───────────────────────────────────────────────────────────


@router.get("/{guild_id}/leveling/rewards", response_model=list[LevelRewardOut])
async def list_rewards(
    guild: Guild = Depends(require_managed_guild),
    repo: LevelRoleRewardRepository = Depends(get_level_role_reward_repository),
):
    """List the guild's level → role mapping, ordered by level ASC.

    Goes straight to the repo because there's no business logic — just a
    SELECT with stable ordering, then snowflake stringification.
    """
    items = await repo.list_by_guild(guild.id)
    return [LevelRewardOut(level=r.level, role_id=str(r.role_id)) for r in items]


@router.post("/{guild_id}/leveling/rewards", response_model=LevelRewardOut)
async def create_reward(
    payload: LevelRewardCreate,
    guild: Guild = Depends(require_managed_guild),
    repo: LevelRoleRewardRepository = Depends(get_level_role_reward_repository),
):
    """Create a level → role mapping, or update it if one already exists at that level.

    The repo's `upsert` is keyed by `(guild_id, level)` via the unique
    constraint, so calling POST twice with the same `level` and a
    different `role_id` replaces the mapping rather than failing — that
    matches how admins actually use this in the dashboard ("change
    which role @level5 grants").
    """
    row = await repo.upsert(guild.id, level=payload.level, role_id=int(payload.role_id))
    return LevelRewardOut(level=row.level, role_id=str(row.role_id))


@router.delete("/{guild_id}/leveling/rewards/{level}", response_model=LevelRewardOut)
async def delete_reward(
    level: int,
    guild: Guild = Depends(require_managed_guild),
    repo: LevelRoleRewardRepository = Depends(get_level_role_reward_repository),
):
    """Remove the reward mapping at `level`, returning the deleted row.

    We do a quick `list_by_guild` + `next(..., None)` lookup so we can
    400/404 cleanly if the level has no mapping. The actual delete then
    runs unconditionally — `delete_by_level` is idempotent at the SQL
    level too.

    The response echoes the row that was deleted (level + role_id) so
    the dashboard can show a "removed @level5 → @Active" toast.

    Raises:
        NotFoundError: When there's no reward mapped to `level` in this
            guild — distinguishes "the level had no mapping" from
            "the mapping was successfully removed".
    """
    items = await repo.list_by_guild(guild.id)
    target = next((r for r in items if r.level == level), None)
    if target is None:
        raise NotFoundError(detail="Reward not found")

    # Grab the role_id *before* deletion so we can echo it back.
    role_id = target.role_id
    await repo.delete_by_level(guild.id, level)
    return LevelRewardOut(level=level, role_id=str(role_id))


# ─── Rank card theme ───────────────────────────────────────────────────


def _theme_out(t) -> RankCardThemeIO:
    """Convert a `GuildRankCardTheme` ORM row to the `RankCardThemeIO` DTO.

    Shared between GET and PUT so both responses come from the same
    shape. Colours are plain strings in both directions; the schema's
    regex pattern validates hex format on PUT.

    Args:
        t: A `GuildRankCardTheme` row. Type-hinted as `Any` (just `t`)
            to keep this module loose from the SQLAlchemy model type.

    Returns:
        A `RankCardThemeIO` Pydantic model.
    """
    return RankCardThemeIO(
        bg_type=t.bg_type,
        bg_color_1=t.bg_color_1,
        bg_color_2=t.bg_color_2,
        accent_color=t.accent_color,
        text_color=t.text_color,
    )


@router.get("/{guild_id}/leveling/rank-card-theme", response_model=RankCardThemeIO)
async def get_theme(
    guild: Guild = Depends(require_managed_guild),
    repo: GuildRankCardThemeRepository = Depends(get_guild_rank_card_theme_repository),
):
    """Return the guild's rank-card theme, creating defaults on first call.

    Same lazy-default pattern as `get_settings` — first access mints a
    row with the bot's default palette so dashboards never see a blank
    page or 404 for a never-customised guild.
    """
    t = await repo.get_or_create(guild.id)
    return _theme_out(t)


@router.put("/{guild_id}/leveling/rank-card-theme", response_model=RankCardThemeIO)
async def update_theme(
    payload: RankCardThemeIO,
    guild: Guild = Depends(require_managed_guild),
    repo: GuildRankCardThemeRepository = Depends(get_guild_rank_card_theme_repository),
):
    """Persist a new rank-card theme for the guild.

    The Pydantic schema enforces hex-color format via `pattern=` regex,
    so by the time we get here the colours are well-formed strings. We
    don't have to re-validate anything — just pass the dump dict to the
    repo's upsert.

    Notice we don't invalidate any cache here. Themes are read on the
    `/rank` slash command path (fresh DB read each time, no cache), so
    a PUT is immediately reflected in subsequent renders without any
    extra wiring.
    """
    t = await repo.upsert(guild.id, payload.model_dump())
    return _theme_out(t)
