"""King of the Hill strategy.

Buy tokens that reach 40-65% bonding curve progress (KOTH zone)
with good fundamentals (unique buyers, velocity, etc.)
"""

import logging
from src.config import Config
from src.token_tracker import TokenInfo
from src.strategies.base import BaseStrategy

logger = logging.getLogger("sniper.koth")


class KingOfTheHillStrategy(BaseStrategy):
    name = "KOTH"

    def __init__(self, config: Config, budget_sol: float):
        super().__init__(config, budget_sol)
        self._koth_candidates: set[str] = set()

    def evaluate(self, token: TokenInfo) -> None:
        self.tokens_evaluated += 1

        # First update any open positions
        self.update_positions(token)

        # Check if token is in KOTH zone
        curve = token.curve_progress_pct
        if curve < self.config.KOTH_MIN_CURVE_PCT or curve > self.config.KOTH_MAX_CURVE_PCT:
            return

        # Already bought or evaluated this one
        if token.mint in self._seen_mints:
            return
        if token.mint in self._koth_candidates:
            return

        self._koth_candidates.add(token.mint)

        # --- Filters ---

        # 1. Unique buyers
        n_buyers = len(token.unique_buyers)
        if n_buyers < self.config.KOTH_MIN_UNIQUE_BUYERS:
            logger.debug(
                "[KOTH] SKIP $%s - only %d buyers (need %d+)",
                token.symbol or token.mint[:8], n_buyers, self.config.KOTH_MIN_UNIQUE_BUYERS,
            )
            return

        # 2. Velocity - must have recent buying activity
        velocity = token.velocity_sol(60)
        if velocity < self.config.KOTH_MIN_VELOCITY:
            logger.debug(
                "[KOTH] SKIP $%s - velocity %.3f SOL/min (need %.3f+)",
                token.symbol or token.mint[:8], velocity, self.config.KOTH_MIN_VELOCITY,
            )
            return

        # 3. Buy/sell ratio - more buys than sells
        if token.total_sells > 0:
            buy_sell_ratio = token.total_buys / max(1, token.total_sells)
            if buy_sell_ratio < 1.5:
                logger.debug(
                    "[KOTH] SKIP $%s - buy/sell ratio %.1f (need 1.5+)",
                    token.symbol or token.mint[:8], buy_sell_ratio,
                )
                return

        # 4. Creator hasn't sold yet
        if token.creator in token.unique_sellers:
            logger.debug(
                "[KOTH] SKIP $%s - creator already selling",
                token.symbol or token.mint[:8],
            )
            return

        self.tokens_passed_filter += 1

        # --- Execute buy ---
        reason = (
            f"KOTH zone {curve:.0f}% | "
            f"{n_buyers} buyers | "
            f"vel {velocity:.2f} SOL/min"
        )
        self._execute_buy(token, reason)

    def on_graduation(self, token: TokenInfo) -> None:
        """If we hold this token and it graduates, sell for profit."""
        for pos in list(self.positions):
            if pos.mint == token.mint:
                self._execute_sell(pos, token, "GRADUATED - selling into hype")
