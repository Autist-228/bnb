"""Base strategy class for paper trading."""

import time
import logging
from dataclasses import dataclass, field
from typing import Optional

from src.config import Config
from src.token_tracker import TokenInfo

logger = logging.getLogger("sniper.strategy")


@dataclass
class Position:
    mint: str
    symbol: str
    entry_price: float  # SOL per token (raw virtual ratio)
    entry_sol: float  # SOL spent
    tokens_bought: float  # approximate tokens received
    entry_time: float
    entry_curve_pct: float

    # Updated as price changes
    current_price: float = 0.0
    current_curve_pct: float = 0.0
    last_update: float = 0.0

    # Exit
    exit_price: float = 0.0
    exit_sol: float = 0.0
    exit_time: float = 0.0
    exit_reason: str = ""
    is_closed: bool = False

    @property
    def pnl_sol(self) -> float:
        if self.is_closed:
            return self.exit_sol - self.entry_sol
        if self.entry_price <= 0:
            return 0.0
        current_value = (self.current_price / self.entry_price) * self.entry_sol
        return current_value - self.entry_sol

    @property
    def pnl_pct(self) -> float:
        if self.entry_sol <= 0:
            return 0.0
        return (self.pnl_sol / self.entry_sol) * 100

    @property
    def hold_time(self) -> float:
        end = self.exit_time if self.is_closed else time.time()
        return end - self.entry_time


@dataclass
class TradeLog:
    strategy: str
    action: str  # BUY / SELL
    mint: str
    symbol: str
    sol_amount: float
    price: float
    curve_pct: float
    timestamp: float
    reason: str = ""
    pnl_sol: float = 0.0


class BaseStrategy:
    """Base class for all trading strategies."""

    name: str = "base"

    def __init__(self, config: Config, budget_sol: float):
        self.config = config
        self.budget_sol = budget_sol
        self.available_sol = budget_sol
        self.positions: list[Position] = []
        self.closed_positions: list[Position] = []
        self.trade_log: list[TradeLog] = []
        self.tokens_evaluated: int = 0
        self.tokens_passed_filter: int = 0
        self._seen_mints: set[str] = set()

    def _can_buy(self) -> bool:
        open_count = len(self.positions)
        return (
            self.available_sol >= self.config.BUY_AMOUNT_SOL
            and open_count < self.config.MAX_POSITIONS
        )

    def _execute_buy(self, token: TokenInfo, reason: str) -> Optional[Position]:
        if not self._can_buy():
            return None
        if token.mint in self._seen_mints:
            return None  # already traded this token

        self._seen_mints.add(token.mint)
        buy_sol = min(self.config.BUY_AMOUNT_SOL, self.available_sol)
        price = token.price_sol
        if price <= 0:
            return None

        # Simulate: tokens = sol_spent / price_per_token
        # But price is virtualSol/virtualToken (lamports ratio)
        # tokens_bought = buy_sol_lamports * virtualTokenReserves / virtualSolReserves
        if token.virtual_sol_reserves <= 0:
            return None
        tokens_bought = (buy_sol * 1e9 * token.virtual_token_reserves) / token.virtual_sol_reserves

        self.available_sol -= buy_sol

        pos = Position(
            mint=token.mint,
            symbol=token.symbol or token.mint[:8],
            entry_price=price,
            entry_sol=buy_sol,
            tokens_bought=tokens_bought,
            entry_time=time.time(),
            entry_curve_pct=token.curve_progress_pct,
            current_price=price,
            current_curve_pct=token.curve_progress_pct,
            last_update=time.time(),
        )
        self.positions.append(pos)

        log_entry = TradeLog(
            strategy=self.name,
            action="BUY",
            mint=token.mint,
            symbol=token.symbol or token.mint[:8],
            sol_amount=buy_sol,
            price=price,
            curve_pct=token.curve_progress_pct,
            timestamp=time.time(),
            reason=reason,
        )
        self.trade_log.append(log_entry)

        logger.info(
            "[%s] BUY $%s @ curve %.1f%% | %.4f SOL | reason: %s",
            self.name, pos.symbol, pos.entry_curve_pct, buy_sol, reason,
        )
        return pos

    def _execute_sell(self, pos: Position, token: TokenInfo, reason: str) -> None:
        price = token.price_sol
        if price <= 0:
            price = pos.current_price

        # Calculate exit value
        if pos.entry_price > 0:
            exit_sol = (price / pos.entry_price) * pos.entry_sol
        else:
            exit_sol = pos.entry_sol

        pos.exit_price = price
        pos.exit_sol = exit_sol
        pos.exit_time = time.time()
        pos.exit_reason = reason
        pos.is_closed = True

        self.available_sol += exit_sol
        self.positions.remove(pos)
        self.closed_positions.append(pos)

        log_entry = TradeLog(
            strategy=self.name,
            action="SELL",
            mint=pos.mint,
            symbol=pos.symbol,
            sol_amount=exit_sol,
            price=price,
            curve_pct=token.curve_progress_pct if token else pos.current_curve_pct,
            timestamp=time.time(),
            reason=reason,
            pnl_sol=pos.pnl_sol,
        )
        self.trade_log.append(log_entry)

        pnl = pos.pnl_sol
        pnl_pct = pos.pnl_pct
        logger.info(
            "[%s] SELL $%s | %+.4f SOL (%+.1f%%) | reason: %s",
            self.name, pos.symbol, pnl, pnl_pct, reason,
        )

    def update_positions(self, token: TokenInfo) -> None:
        """Update open positions and check exit conditions."""
        for pos in list(self.positions):
            if pos.mint != token.mint:
                continue

            pos.current_price = token.price_sol
            pos.current_curve_pct = token.curve_progress_pct
            pos.last_update = time.time()

            # Take profit
            if pos.pnl_pct >= self.config.TAKE_PROFIT_PCT:
                self._execute_sell(pos, token, f"TAKE_PROFIT ({pos.pnl_pct:+.1f}%)")
                continue

            # Stop loss
            if pos.pnl_pct <= -self.config.STOP_LOSS_PCT:
                self._execute_sell(pos, token, f"STOP_LOSS ({pos.pnl_pct:+.1f}%)")
                continue

            # Timeout
            if pos.hold_time >= self.config.TIMEOUT_SECONDS:
                self._execute_sell(pos, token, f"TIMEOUT ({pos.hold_time:.0f}s)")
                continue

    def check_timeouts(self) -> None:
        """Force-close positions that have timed out (no recent data)."""
        for pos in list(self.positions):
            if pos.hold_time >= self.config.TIMEOUT_SECONDS:
                # Create a dummy token for sell
                dummy = TokenInfo(mint=pos.mint, symbol=pos.symbol)
                dummy.virtual_sol_reserves = int(pos.current_price * pos.current_price) if pos.current_price else 0
                dummy.virtual_token_reserves = 1
                pos.exit_price = pos.current_price
                pos.exit_sol = pos.entry_sol * 0.8  # assume 20% loss on timeout
                pos.exit_time = time.time()
                pos.exit_reason = f"TIMEOUT_STALE ({pos.hold_time:.0f}s)"
                pos.is_closed = True
                self.available_sol += pos.exit_sol
                self.positions.remove(pos)
                self.closed_positions.append(pos)
                logger.info(
                    "[%s] FORCE_CLOSE $%s | timeout with stale data",
                    self.name, pos.symbol,
                )

    def evaluate(self, token: TokenInfo) -> None:
        """Override in subclass: decide whether to buy this token."""
        raise NotImplementedError

    def on_graduation(self, token: TokenInfo) -> None:
        """Override in subclass: handle token graduation."""
        pass

    # --- Reporting ---

    @property
    def total_pnl_sol(self) -> float:
        closed = sum(p.pnl_sol for p in self.closed_positions)
        unrealized = sum(p.pnl_sol for p in self.positions)
        return closed + unrealized

    @property
    def realized_pnl_sol(self) -> float:
        return sum(p.pnl_sol for p in self.closed_positions)

    @property
    def win_count(self) -> int:
        return sum(1 for p in self.closed_positions if p.pnl_sol > 0)

    @property
    def loss_count(self) -> int:
        return sum(1 for p in self.closed_positions if p.pnl_sol <= 0)

    def summary(self, sol_price_usd: float) -> str:
        lines = [
            f"=== {self.name.upper()} STRATEGY ===",
            f"  Budget: {self.budget_sol:.4f} SOL",
            f"  Available: {self.available_sol:.4f} SOL",
            f"  Tokens evaluated: {self.tokens_evaluated}",
            f"  Passed filter: {self.tokens_passed_filter}",
            f"  Total trades: {len(self.trade_log)}",
            f"  Open positions: {len(self.positions)}",
            f"  Closed positions: {len(self.closed_positions)}",
            f"  Wins: {self.win_count} | Losses: {self.loss_count}",
            f"  Realized P&L: {self.realized_pnl_sol:+.6f} SOL (${self.realized_pnl_sol * sol_price_usd:+.2f})",
            f"  Total P&L (incl unrealized): {self.total_pnl_sol:+.6f} SOL (${self.total_pnl_sol * sol_price_usd:+.2f})",
        ]
        if self.positions:
            lines.append("  Open positions:")
            for p in self.positions:
                lines.append(
                    f"    $%s: %+.1f%% | curve %.1f%% | hold %.0fs"
                    % (p.symbol, p.pnl_pct, p.current_curve_pct, p.hold_time)
                )
        if self.closed_positions:
            lines.append("  Recent closed:")
            for p in self.closed_positions[-5:]:
                lines.append(
                    f"    $%s: %+.4f SOL (%+.1f%%) | %s"
                    % (p.symbol, p.pnl_sol, p.pnl_pct, p.exit_reason)
                )
        return "\n".join(lines)
