"""Solana Pump.fun Sniper Bot - Paper Trading Mode.

Three strategies:
  1. KOTH (King of the Hill) - Buy tokens at 40-65% bonding curve with momentum
  2. VELOCITY - Detect and ride sudden buy spikes
  3. MIGRATION - Snipe tokens at the exact graduation moment

Usage:
  python main.py --strategy koth --duration 600
  python main.py --strategy velocity --duration 600
  python main.py --strategy migration --duration 600
  python main.py --strategy all --duration 600
"""

import argparse
import asyncio
import logging
import sys

from src.config import Config
from src.paper_trader import PaperTrader
from src.utils import setup_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pump.fun Sniper Bot - Paper Trading",
    )
    parser.add_argument(
        "--strategy",
        type=str,
        default="all",
        choices=["koth", "velocity", "migration", "all"],
        help="Strategy to run (default: all)",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=600,
        help="Duration in seconds (default: 600 = 10 minutes)",
    )
    parser.add_argument(
        "--budget",
        type=float,
        default=None,
        help="Budget in USD (default: from .env or 50)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    level = logging.DEBUG if args.debug else logging.INFO
    setup_logging(level)

    logger = logging.getLogger("sniper.main")

    config = Config()
    if args.budget is not None:
        config.BUDGET_USD = args.budget

    if args.strategy == "all":
        strategies = ["koth", "velocity", "migration"]
    else:
        strategies = [args.strategy]

    logger.info("Pump.fun Sniper Bot - PAPER TRADING MODE")
    logger.info(
        "Strategies: %s | Duration: %ds | Budget: $%.2f (%.4f SOL)",
        ", ".join(s.upper() for s in strategies),
        args.duration,
        config.BUDGET_USD,
        config.budget_sol,
    )

    trader = PaperTrader(
        config=config,
        strategies=strategies,
        duration_seconds=args.duration,
    )

    try:
        report = asyncio.run(trader.run())
        print(report)
    except KeyboardInterrupt:
        logger.info("Stopped by user")
    except Exception as e:
        logger.critical("Fatal error: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
