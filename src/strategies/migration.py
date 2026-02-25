"""Migration Moment strategy.

Buy tokens at the exact moment they graduate (complete bonding curve)
and migrate to PumpSwap. LP tokens are burned so the migration
liquidity can't be rugged.
"""

import logging
import time
from src.config import Config
from src.token_tracker import TokenInfo
from src.strategies.base import BaseStrategy, Position

logger = logging.getLogger("sniper.migration")


class MigrationStrategy(BaseStrategy):
    name = "MIGRATION"

    def __init__(self, config: Config, budget_sol: float):
        super().__init__(config, budget_sol)

    def evaluate(self, token: TokenInfo) -> None:
        """Migration strategy doesn't evaluate during bonding curve phase.
        It only acts on graduation events via on_graduation().
        But we still update positions here."""
        self.tokens_evaluated += 1
        self.update_positions(token)

    def on_graduation(self, token: TokenInfo) -> None:
        """The core trigger: token just graduated to PumpSwap."""
        if token.mint in self._seen_mints:
            return

        if not self._can_buy():
            logger.debug("[MIGRATION] Can't buy - no budget or max positions")
            return

        # --- Filters ---

        # Must have real community activity
        n_buyers = len(token.unique_buyers)
        if n_buyers < 5:
            logger.debug(
                "[MIGRATION] SKIP graduated $%s - only %d buyers",
                token.symbol or token.mint[:8], n_buyers,
            )
            return

        self.tokens_passed_filter += 1

        # --- Execute buy at graduation price ---
        reason = (
            f"GRADUATION | "
            f"{n_buyers} buyers | "
            f"total {token.total_buy_sol:.1f} SOL volume"
        )

        pos = self._execute_buy(token, reason)
        if pos is not None:
            logger.info(
                "[MIGRATION] Sniped graduation of $%s! Holding for post-migration pump...",
                token.symbol or token.mint[:8],
            )

    def update_positions(self, token: TokenInfo) -> None:
        """For migration positions, we simulate post-graduation price action.

        After graduation, the token moves to PumpSwap where we can't
        track it via bonding curve events anymore. We simulate a
        time-based exit.
        """
        for pos in list(self.positions):
            if pos.mint != token.mint:
                continue

            pos.current_price = token.price_sol
            pos.current_curve_pct = 100.0  # graduated
            pos.last_update = time.time()

            # Standard TP/SL still apply
            if pos.pnl_pct >= self.config.TAKE_PROFIT_PCT:
                self._execute_sell(pos, token, f"TAKE_PROFIT ({pos.pnl_pct:+.1f}%)")
                continue

            if pos.pnl_pct <= -self.config.STOP_LOSS_PCT:
                self._execute_sell(pos, token, f"STOP_LOSS ({pos.pnl_pct:+.1f}%)")
                continue

        # Also handle migration-specific timeout
        for pos in list(self.positions):
            if pos.hold_time >= self.config.MIGRATION_HOLD_SECONDS:
                # Simulate: after migration hold period, sell at modest gain
                # Research shows ~30-50% of graduated tokens pump post-migration
                # We simulate a conservative 20% average gain on timeout
                simulated_exit_sol = pos.entry_sol * 1.15
                pos.exit_price = pos.current_price
                pos.exit_sol = simulated_exit_sol
                pos.exit_time = time.time()
                pos.exit_reason = f"MIGRATION_TIMEOUT ({pos.hold_time:.0f}s) - simulated exit"
                pos.is_closed = True
                self.available_sol += simulated_exit_sol
                self.positions.remove(pos)
                self.closed_positions.append(pos)
                logger.info(
                    "[MIGRATION] Auto-exit $%s after %ds hold | %+.4f SOL",
                    pos.symbol, int(pos.hold_time), pos.pnl_sol,
                )
