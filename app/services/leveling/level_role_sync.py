"""Sync a member's level-reward roles after their level changed.

A guild can configure rewards like "level 5 → @Active, level 10 → @Veteran".
When a member's level changes — by chatting up to a level-up, by an admin
PATCH/DELETE on their XP, or by a reset — we need to make Discord reflect
the new state: grant any roles they newly qualify for, strip any they
no longer qualify for.

Two modes are supported (per-guild setting):

    LevelRoleMode.STACKING   → keep every reward they qualify for.
                                Level 12 member with rewards at 5/10/15
                                → holds @level5 AND @level10.

    LevelRoleMode.REPLACING  → keep only the *highest* reward they
                                qualify for. Same member as above
                                → holds @level10 only.

Algorithm at a glance (see `apply` for the actual code):

    1. Load every reward row for the guild, ordered by level ASC.
    2. Compute the *target* set of role_ids for `new_level` + mode.
    3. Read the member's *current* role_ids from Discord.
    4. Diff: to_add = target - current
             to_remove = (managed ∩ current) - target
       The `managed` mask ensures we never touch roles the bot didn't grant.
    5. Apply add/remove one role at a time. Errors are handled per-role:
         - DiscordNotFound on add → the reward role was deleted on Discord;
           drop the orphan reward row so we stop trying (self-heal).
         - DiscordForbidden on either → log a warning, continue. One bad
           permission cannot crash a level-up.

Key invariant: **the bot never strips a role it didn't grant.** Roles
given manually (mod gives @VIP, server boost gives @Booster, etc.) survive
every sync because they aren't in `managed_role_ids`.
"""

import logging
import uuid

from app.core.enums import LevelRoleMode
from app.discord_io.client import DiscordClient
from app.discord_io.errors import DiscordError, DiscordForbidden, DiscordNotFound
from app.repositories.level_role_reward import LevelRoleRewardRepository

log = logging.getLogger(__name__)


class LevelRoleSync:
    """Diffs and applies level-reward roles for one member.

    Stateless besides its two dependencies — instantiated fresh by
    `LevelingService` per call. Idempotent: calling `apply()` twice in a
    row with the same args is a no-op the second time.
    """

    def __init__(self, reward_repo: LevelRoleRewardRepository, discord_io: DiscordClient):
        """Store the repo + Discord client dependencies.

        Args:
            reward_repo: Reads `level_role_reward` rows for the guild and
                deletes orphan rows when self-healing.
            discord_io: Used to read the member's current roles and to
                add/remove individual roles.
        """
        self.reward_repo = reward_repo
        self.discord_io = discord_io

    async def apply(
        self,
        *,
        guild_id: uuid.UUID,
        guild_discord_id: int,
        user_id: int,
        new_level: int,
        mode: LevelRoleMode,
    ) -> None:
        """Bring the member's role state in line with `new_level`.

        Safe to call:
            - After a normal chat-driven level-up (`new_level` > old_level).
            - After admin XP override (`set_member_xp` recomputes the level
              and calls this).
            - After admin reset (`reset_member` passes `new_level=0` which
              causes `target_role_ids` to be empty → everything managed
              gets stripped).

        Args:
            guild_id: Internal UUID of the guild — used for the `reward_repo`
                queries (which key by internal id).
            guild_discord_id: Discord snowflake of the guild — used for the
                `discord_io` calls (which take Discord IDs).
            user_id: Discord snowflake of the member.
            new_level: The level the member is now at. Determines the
                target set of roles.
            mode: STACKING or REPLACING (see module docstring).

        Returns:
            None. Errors are absorbed per-role (see `try/except` blocks),
            so the function returning successfully means "we did the best
            we could", not "every role operation succeeded". Operators
            should watch the logs for `Forbidden` warnings.

        Example:
            # Member levelled up to 12 in a guild with rewards at 5/10/15:
            >>> await sync.apply(guild_id=gid, guild_discord_id=999,
            ...                  user_id=42, new_level=12,
            ...                  mode=LevelRoleMode.STACKING)
            # → adds @level5 + @level10 if missing; removes nothing
            #   because we only just grew into them.
        """
        # Pull every reward row for the guild. Empty list → nothing managed
        # by leveling at all → nothing to do.
        rewards = await self.reward_repo.list_by_guild(guild_id)
        if not rewards:
            return

        # Filter to the rewards the member qualifies for at `new_level`.
        # Rewards above their level stay out of `target`.
        eligible = [r for r in rewards if r.level <= new_level]

        # Compute the *target* role set based on mode.
        if mode == LevelRoleMode.REPLACING:
            # Keep only the single highest reward. `eligible` is already
            # sorted by level ASC (the repo's `list_by_guild` enforces it),
            # so `eligible[-1]` is the top one. Empty → empty target
            # (member has no roles to hold).
            target_role_ids = {eligible[-1].role_id} if eligible else set()
        else:
            # STACKING: hold every reward they qualify for.
            target_role_ids = {r.role_id for r in eligible}

        # `managed` is the universe of roles this bot might add/remove.
        # Anything outside this set is off-limits — see module-level
        # invariant about not touching manually-granted roles.
        managed_role_ids = {r.role_id for r in rewards}

        # Live read of the member's current role IDs. Note: this is a single
        # gateway-cache hit if the bot has the member cached, otherwise a
        # REST call. Either way, much cheaper than asking Discord per role.
        current_role_ids = await self.discord_io.get_member_role_ids(guild_discord_id, user_id)

        # Diff:
        # - to_add: in target, not currently held → grant.
        # - to_remove: bot-managed AND currently held BUT not in target.
        #   The `managed_role_ids &` filter is what protects unrelated roles.
        to_add = target_role_ids - current_role_ids
        to_remove = (managed_role_ids & current_role_ids) - target_role_ids

        # `_guild_role_ids` is lazy-loaded the first time we need to
        # disambiguate a DiscordNotFound — Discord's API returns 404 for
        # *either* "role doesn't exist" *or* "member just left", and the
        # two cases need opposite responses. Loaded at most once per call.
        guild_role_ids: set[int] | None = None

        async def _role_still_exists(role_id: int) -> bool:
            # Returns True if the role is still in the guild's role list.
            # On lookup failure we return True ("be conservative"): wrongly
            # keeping a reward row beats wrongly deleting a valid one.
            nonlocal guild_role_ids
            if guild_role_ids is None:
                try:
                    roles = await self.discord_io.list_roles(guild_discord_id)
                    guild_role_ids = {r.discord_id for r in roles}
                except DiscordError:
                    log.warning(
                        "list_roles failed for guild %s; skipping orphan cleanup",
                        guild_discord_id,
                    )
                    guild_role_ids = set()
                    return True  # conservative — don't delete
            return role_id in guild_role_ids

        # Apply additions one at a time. We don't batch because Discord's
        # bulk role API requires the *complete* desired role list; using
        # per-role calls keeps the algorithm simple and the failure mode
        # per-role rather than all-or-nothing.
        for role_id in to_add:
            try:
                await self.discord_io.add_role(guild_discord_id, user_id, role_id)
            except DiscordNotFound:
                # 404 here is ambiguous — could mean the role was deleted on
                # Discord (true orphan, prune the reward row) *or* the member
                # just left the guild (do nothing, the reward is still valid
                # for everyone else). Check the role list to tell them apart.
                if await _role_still_exists(role_id):
                    log.warning(
                        "Could not add role %s to user %s in guild %s — member "
                        "may have left; reward kept",
                        role_id,
                        user_id,
                        guild_discord_id,
                    )
                else:
                    log.info(
                        "Role %s deleted on Discord; removing orphan reward row",
                        role_id,
                    )
                    await self.reward_repo.delete_by_role(guild_id, role_id=role_id)
            except DiscordForbidden:
                # Permission problem (role above the bot's top role, or
                # missing MANAGE_ROLES). Log and continue — the level-up
                # itself already succeeded; this is a delivery hiccup.
                log.warning(
                    "Forbidden adding role %s to user %s in guild %s — skipping",
                    role_id,
                    user_id,
                    guild_discord_id,
                )

        # Apply removals. Same per-role failure handling as adds.
        for role_id in to_remove:
            try:
                await self.discord_io.remove_role(guild_discord_id, user_id, role_id)
            except (DiscordNotFound, DiscordForbidden):
                # Either the role vanished (someone deleted it server-side)
                # or we lack permission to remove it. Either way, the
                # right answer is to log and move on rather than crash.
                log.warning("Could not remove role %s from user %s — skipping", role_id, user_id)
