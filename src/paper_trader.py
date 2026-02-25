"""Paper trading engine - orchestrates strategies against live data."""

import asyncio
import time
import logging
from typing import Optional

from src.config import Config
from src.listener import PumpFunListener
from src.token_tracker import TokenTracker
from src.events import CreateEvent, TradeEvent, CompleteEvent
from src.strategies.base import BaseStrategy
from src.strategies.koth import KingOfTheHillStrategy
from src.strategies.velocity import VelocityStrategy
from src.strategies.migration import MigrationStrategy

logger = logging.getLogger("sniper.paper")


class PaperTrader:
    """Run paper trading with one or more strategies against live pump.fun data."""

    def __init__(
        self,
        config: Config,
        strategies: list[str],
        duration_seconds: int = 600,
    ):
        self.config = config
        self.duration = duration_seconds
        self.listener = PumpFunListener(config)
        self.tracker = TokenTracker()

        # Split budget equally among strategies
        n_strats = len(strategies)
        budget_per = config.budget_sol / n_strats if n_strats > 0 else config.budget_sol

        self.strategies: list[BaseStrategy] = []
        for name in strategies:
            if name == "koth":
                self.strategies.append(KingOfTheHillStrategy(config, budget_per))
            elif name == "velocity":
                self.strategies.append(VelocityStrategy(config, budget_per))
            elif name == "migration":
                self.strategies.append(MigrationStrategy(config, budget_per))
            else:
                logger.warning("Unknown strategy: %s", name)

        self.start_time: float = 0
        self.events_processed: int = 0
        self._status_interval: int = 30  # print status every N seconds
        self._last_status: float = 0

    async def run(self) -> str:
        """Run paper trading for the configured duration. Returns report."""
        self.start_time = time.time()
        end_time = self.start_time + self.duration

        strat_names = ", ".join(s.name for s in self.strategies)
        logger.info(
            "Starting paper trading | strategies: [%s] | duration: %ds | budget: %.4f SOL ($%.2f)",
            strat_names, self.duration, self.config.budget_sol, self.config.BUDGET_USD,
        )

        try:
            async for event in self.listener.listen():
                if time.time() >= end_time:
                    logger.info("Duration reached (%ds). Stopping...", self.duration)
                    break

                self._process_event(event)
                self.events_processed += 1

                # Periodic status
                now = time.time()
                if now - self._last_status >= self._status_interval:
                    self._print_status()
                    self._last_status = now

                # Check timeouts on all strategies
                for strat in self.strategies:
                    strat.check_timeouts()

        except asyncio.CancelledError:
            logger.info("Paper trading cancelled")
        finally:
            await self.listener.disconnect()

        # Close any remaining positions at last known price
        self._close_all_positions()

        return self.generate_report()

    def _process_event(self, event: CreateEvent | TradeEvent | CompleteEvent) -> None:
        if isinstance(event, CreateEvent):
            token = self.tracker.handle_create(event)
            # Create events don't trigger strategy evaluation

        elif isinstance(event, TradeEvent):
            token = self.tracker.handle_trade(event)
            if token is not None:
                for strat in self.strategies:
                    strat.evaluate(token)

        elif isinstance(event, CompleteEvent):
            token = self.tracker.handle_complete(event)
            if token is not None:
                for strat in self.strategies:
                    strat.on_graduation(token)

    def _close_all_positions(self) -> None:
        """Force-close any remaining positions at end of session."""
        for strat in self.strategies:
            for pos in list(strat.positions):
                token = self.tracker.get_token(pos.mint)
                if token is not None:
                    strat._execute_sell(pos, token, "SESSION_END")
                else:
                    # No token data, close at last known price
                    pos.exit_price = pos.current_price
                    pos.exit_sol = pos.entry_sol * 0.9  # assume 10% loss
                    pos.exit_time = time.time()
                    pos.exit_reason = "SESSION_END (no data)"
                    pos.is_closed = True
                    strat.available_sol += pos.exit_sol
                    strat.positions.remove(pos)
                    strat.closed_positions.append(pos)

    def _print_status(self) -> None:
        elapsed = time.time() - self.start_time
        remaining = max(0, self.duration - elapsed)
        logger.info(
            "--- STATUS | %.0fs elapsed | %.0fs remaining | "
            "%d events | %d tokens tracked | %d graduations ---",
            elapsed, remaining,
            self.events_processed,
            self.tracker.active_count(),
            self.tracker.total_graduations,
        )
        for strat in self.strategies:
            open_pos = len(strat.positions)
            closed = len(strat.closed_positions)
            pnl = strat.total_pnl_sol
            logger.info(
                "  [%s] open: %d | closed: %d | P&L: %+.6f SOL ($%+.2f)",
                strat.name, open_pos, closed, pnl, pnl * self.config.SOL_PRICE_USD,
            )

    def generate_report(self) -> str:
        elapsed = time.time() - self.start_time
        sol_price = self.config.SOL_PRICE_USD

        lines = [
            "",
            "=" * 60,
            "  PAPER TRADING REPORT",
            "=" * 60,
            f"  Duration: {elapsed:.0f} seconds ({elapsed/60:.1f} minutes)",
            f"  Budget: {self.config.budget_sol:.4f} SOL (${self.config.BUDGET_USD:.2f})",
            f"  SOL price: ${sol_price:.2f}",
            f"  Events processed: {self.events_processed}",
            f"  Tokens seen: {self.tracker.total_creates} created, "
            f"{self.tracker.active_count()} tracked",
            f"  Trades observed: {self.tracker.total_trades}",
            f"  Graduations: {self.tracker.total_graduations}",
            f"  WebSocket disconnects: {self.listener.disconnects}",
            "",
        ]

        total_pnl = 0.0
        total_trades = 0
        total_wins = 0
        total_losses = 0

        for strat in self.strategies:
            lines.append(strat.summary(sol_price))
            lines.append("")
            total_pnl += strat.total_pnl_sol
            total_trades += len(strat.trade_log)
            total_wins += strat.win_count
            total_losses += strat.loss_count

        lines.extend([
            "=" * 60,
            "  COMBINED RESULTS",
            "=" * 60,
            f"  Total trades: {total_trades}",
            f"  Total wins: {total_wins} | losses: {total_losses}",
            f"  Win rate: {(total_wins / max(1, total_wins + total_losses)) * 100:.0f}%",
            f"  Combined P&L: {total_pnl:+.6f} SOL (${total_pnl * sol_price:+.2f})",
            f"  ROI: {(total_pnl / self.config.budget_sol) * 100:+.2f}%",
            "=" * 60,
            "",
        ])

        # Trade log
        all_trades = []
        for strat in self.strategies:
            all_trades.extend(strat.trade_log)
        all_trades.sort(key=lambda t: t.timestamp)

        if all_trades:
            lines.append("TRADE LOG:")
            lines.append("-" * 80)
            for t in all_trades:
                ts = time.strftime("%H:%M:%S", time.localtime(t.timestamp))
                pnl_str = f" P&L: {t.pnl_sol:+.4f} SOL" if t.action == "SELL" else ""
                lines.append(
                    f"  {ts} [{t.strategy:10s}] {t.action:4s} ${t.symbol:10s} "
                    f"| {t.sol_amount:.4f} SOL | curve {t.curve_pct:.0f}%{pnl_str}"
                    f" | {t.reason}"
                )
            lines.append("-" * 80)
        else:
            lines.append("NO TRADES EXECUTED during this session.")
            lines.append("This could mean:")
            lines.append("  - Filters are too strict for the current market conditions")
            lines.append("  - Session was too short to see qualifying tokens")
            lines.append("  - Try adjusting filter parameters in .env")

        return "\n".join(lines)
