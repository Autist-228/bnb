"""Velocity Spike strategy.

Detect sudden bursts of buying activity on a token and ride the wave.
"""

import logging
from src.config import Config
from src.token_tracker import TokenInfo
from src.strategies.base import BaseStrategy

logger = logging.getLogger("sniper.velocity")


class VelocityStrategy(BaseStrategy):
    name = "VELOCITY"

    def __init__(self, config: Config, budget_sol: float):
        super().__init__(config, budget_sol)

    def evaluate(self, token: TokenInfo) -> None:
        self.tokens_evaluated += 1

        # Update open positions
        self.update_positions(token)

        # Already traded
        if token.mint in self._seen_mints:
            return

        # Minimum curve progress - token must have some traction
        curve = token.curve_progress_pct
        if curve < self.config.VELOCITY_MIN_CURVE_PCT:
            return

        # Don't buy tokens that are about to graduate (too expensive)
        if curve > 85:
            return

        # Need enough trade history to measure velocity
        if len(token.trade_history) < 5:
            return

        # --- Detect velocity spike ---
        spike_ratio = token.velocity_spike(
            window=self.config.VELOCITY_WINDOW_SECONDS,
            lookback=300,
        )

        if spike_ratio < self.config.VELOCITY_SPIKE_MULTIPLIER:
            return

        # Recent velocity in absolute terms
        recent_vel = token.velocity_sol(self.config.VELOCITY_WINDOW_SECONDS)
        if recent_vel < 0.1:  # At least 0.1 SOL in recent window
            return

        # --- Filters ---

        # Unique buyers
        n_buyers = len(token.unique_buyers)
        if n_buyers < self.config.VELOCITY_MIN_UNIQUE_BUYERS:
            logger.debug(
                "[VELOCITY] SKIP $%s - only %d buyers",
                token.symbol or token.mint[:8], n_buyers,
            )
            return

        # Check it's organic - not one whale
        # Recent buys should be from multiple wallets
        recent_buyers = set()
        for trade in token.trade_history[-10:]:
            if trade.is_buy:
                recent_buyers.add(trade.user)
        if len(recent_buyers) < 3:
            logger.debug(
                "[VELOCITY] SKIP $%s - only %d recent unique buyers (whale?)",
                token.symbol or token.mint[:8], len(recent_buyers),
            )
            return

        # Creator hasn't dumped
        if token.creator in token.unique_sellers:
            logger.debug(
                "[VELOCITY] SKIP $%s - creator selling",
                token.symbol or token.mint[:8],
            )
            return

        self.tokens_passed_filter += 1

        # --- Execute buy ---
        reason = (
            f"SPIKE {spike_ratio:.1f}x | "
            f"vel {recent_vel:.2f} SOL/min | "
            f"curve {curve:.0f}% | "
            f"{n_buyers} buyers"
        )
        self._execute_buy(token, reason)

    def on_graduation(self, token: TokenInfo) -> None:
        for pos in list(self.positions):
            if pos.mint == token.mint:
                self._execute_sell(pos, token, "GRADUATED - taking profit")
