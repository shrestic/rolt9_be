"""Mini-games facade — validate the bet, debit it, run the game, credit a win.

Coins move through `WalletRepository.add_balance` directly (debit the bet first
so you can never bet more than you hold; credit the payout on a win) — both in
the caller's transaction, so a round never creates or loses coins. No
CurrencyService coupling. The RNG is injectable for deterministic tests.
"""

import random
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from app.repositories.guild import GuildRepository
from app.repositories.minigame_config import MinigameConfigRepository
from app.repositories.user_wallet import WalletRepository
from app.services.minigames.minigame_logic import (
    Outcome,
    play_coinflip,
    play_slots,
    play_taixiu,
)


@dataclass(frozen=True)
class GameResult:
    """The outcome of a single game round, including post-round wallet state.

    Attributes:
        won:     True if the player beat the house.
        payout:  Coins credited back on a win (0 on a loss).
        net:     Net coin change = payout - bet.  Negative means the player lost.
        balance: The player's wallet balance after the round settles.
        detail:  Human-facing roll description, e.g. "Ngửa", "🎲 6+4+1=11 (Tài)".
    """

    won: bool
    payout: int
    net: int
    balance: int
    detail: str


class MinigameService:
    """Facade that wires bet validation, wallet debits/credits, and game logic.

    Typical call flow for any game:
      1. Resolve the guild UUID from the Discord snowflake.
      2. Fetch (or create) the per-guild minigame config and check `enabled`.
      3. Validate bet is within [min_bet, max_bet].
      4. Atomically debit the bet — returns False if insufficient funds.
      5. Run the pure game function (deterministic when `rng` is injected).
      6. Credit payout only on a win.
      7. Return a `GameResult` with the updated balance.

    The RNG is a plain `random.Random` by default; pass a scripted stub in tests
    so you can assert exact outcomes without seeding.
    """

    def __init__(
        self,
        *,
        guild_repo: GuildRepository,
        config_repo: MinigameConfigRepository,
        wallet_repo: WalletRepository,
        rng: random.Random | None = None,
    ):
        self.guild_repo = guild_repo
        self.config_repo = config_repo
        self.wallet_repo = wallet_repo
        # Fall back to a fresh Random() so production never touches the global RNG.
        self._rng = rng or random.Random()

    # ------------------------------------------------------------------
    # Internal helper
    # ------------------------------------------------------------------

    async def _play(
        self, *, guild_discord_id: int, user_id: int, bet: int, game: Callable[[], Outcome]
    ) -> GameResult:
        """Shared pipeline: validate → debit → play → (maybe) credit → return.

        `game` is a zero-arg callable that wraps the pure game function with the
        already-captured rng, bet, and choice so the call site stays clean.
        """
        # 1. Resolve guild — raises if not registered.
        guild = await self.guild_repo.get_by_discord_id(guild_discord_id)
        if guild is None:
            raise ValueError("Server chưa đăng ký với bot.")

        # 2. Check config / enabled flag.
        cfg = await self.config_repo.get(guild.id)
        if cfg is None or not cfg.enabled:
            raise ValueError("Mini-games chưa được bật trên server này.")

        # 3. Validate bet range.
        if bet < cfg.min_bet or bet > cfg.max_bet:
            raise ValueError(f"Cược phải trong khoảng {cfg.min_bet:,}–{cfg.max_bet:,}.")

        # 4. Atomically debit the bet.  WalletRepository returns False when the
        #    player's balance is too low — the balance never goes negative.
        ok = await self.wallet_repo.add_balance(guild.id, user_id, -bet)
        if not ok:
            # Fetch balance for a helpful error message.
            wallet = await self.wallet_repo.get(guild.id, user_id)
            have = wallet.balance if wallet else 0
            raise ValueError(f"Không đủ coin — cược {bet:,}, bạn có {have:,}.")

        # 5. Run the pure game function.
        outcome = game()

        # 6. Credit payout only if the player won (a loss leaves balance = balance - bet).
        if outcome.won:
            await self.wallet_repo.add_balance(guild.id, user_id, outcome.payout)

        # 7. Read the settled balance and return a rich result object.
        wallet = await self.wallet_repo.get(guild.id, user_id)
        balance = wallet.balance if wallet else 0
        return GameResult(
            won=outcome.won,
            payout=outcome.payout,
            # net = 0 on a loss (payout is 0), caller can compute -bet if needed
            # but the spec says net = payout - bet so a loss is negative.
            net=outcome.payout - bet,
            balance=balance,
            detail=outcome.detail,
        )

    # ------------------------------------------------------------------
    # Public game methods
    # ------------------------------------------------------------------

    async def play_coinflip(
        self, *, guild_discord_id: int, user_id: int, bet: int, choice: str
    ) -> GameResult:
        """50/50 coin flip.  `choice` must be "heads" or "tails"; win pays ×1.9."""
        return await self._play(
            guild_discord_id=guild_discord_id,
            user_id=user_id,
            bet=bet,
            game=lambda: play_coinflip(self._rng, bet, choice),
        )

    async def play_taixiu(
        self, *, guild_discord_id: int, user_id: int, bet: int, choice: str
    ) -> GameResult:
        """Tài xỉu (3 dice).  `choice` must be "tai" (≥11) or "xiu" (≤10); win pays ×1.9."""
        return await self._play(
            guild_discord_id=guild_discord_id,
            user_id=user_id,
            bet=bet,
            game=lambda: play_taixiu(self._rng, bet, choice),
        )

    async def play_slots(self, *, guild_discord_id: int, user_id: int, bet: int) -> GameResult:
        """3-reel slot machine.  3-match → ×10, any-2-match → ×1.6, else loss."""
        return await self._play(
            guild_discord_id=guild_discord_id,
            user_id=user_id,
            bet=bet,
            game=lambda: play_slots(self._rng, bet),
        )

    # ------------------------------------------------------------------
    # Config helpers (used by REST endpoints / admin commands)
    # ------------------------------------------------------------------

    async def get_config(self, *, guild_id: uuid.UUID):
        """Return the config for this guild, creating defaults on first access."""
        return await self.config_repo.get_or_create(guild_id)

    async def update_config(self, *, guild_id: uuid.UUID, data: dict):
        """Patch the config with the supplied fields dict; returns the updated row."""
        return await self.config_repo.upsert(guild_id, data)
