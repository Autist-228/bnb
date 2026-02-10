import argparse
import asyncio
import logging
import sys

from src.config import BotConfig
from src.bot import SniperBot
from src.utils import setup_logging

logger = logging.getLogger("sniper.main")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="BNB Sniper Bot - PancakeSwap V2 + ML",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py
  python main.py --buy-amount 0.05 --min-liquidity 2000
  python main.py --ml-score 0.8 --take-profit 150 --stop-loss 20
  python main.py --poll-interval 50 --gas-price 7
        """,
    )

    parser.add_argument(
        "--buy-amount",
        type=float,
        default=None,
        help="BNB amount per buy (default: from .env or 0.1)",
    )
    parser.add_argument(
        "--min-liquidity",
        type=float,
        default=None,
        help="Minimum liquidity in BNB (default: from .env or 1500)",
    )
    parser.add_argument(
        "--ml-score",
        type=float,
        default=None,
        help="Minimum ML score to buy (0.0-1.0, default: 0.7)",
    )
    parser.add_argument(
        "--slippage",
        type=float,
        default=None,
        help="Slippage tolerance %% (default: 12)",
    )
    parser.add_argument(
        "--gas-price",
        type=int,
        default=None,
        help="Gas price in gwei (default: 5)",
    )
    parser.add_argument(
        "--take-profit",
        type=float,
        default=None,
        help="Take profit %% (default: 100)",
    )
    parser.add_argument(
        "--stop-loss",
        type=float,
        default=None,
        help="Stop loss %% (default: 30)",
    )
    parser.add_argument(
        "--max-buy-tax",
        type=float,
        default=None,
        help="Max buy tax %% (default: 10)",
    )
    parser.add_argument(
        "--max-sell-tax",
        type=float,
        default=None,
        help="Max sell tax %% (default: 10)",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=None,
        help="Polling interval in ms (default: 100)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    return parser.parse_args()


def main():
    args = parse_args()

    log_level = logging.DEBUG if args.debug else logging.INFO
    setup_logging(log_level)

    config = BotConfig()

    if args.buy_amount is not None:
        config.buy_amount_bnb = args.buy_amount
    if args.min_liquidity is not None:
        config.min_liquidity_bnb = args.min_liquidity
    if args.ml_score is not None:
        config.ml_min_score = args.ml_score
    if args.slippage is not None:
        config.slippage_percent = args.slippage
    if args.gas_price is not None:
        config.gas_price_gwei = args.gas_price
    if args.take_profit is not None:
        config.take_profit_percent = args.take_profit
    if args.stop_loss is not None:
        config.stop_loss_percent = args.stop_loss
    if args.max_buy_tax is not None:
        config.max_buy_tax = args.max_buy_tax
    if args.max_sell_tax is not None:
        config.max_sell_tax = args.max_sell_tax
    if args.poll_interval is not None:
        config.poll_interval_ms = args.poll_interval

    if not config.private_key:
        logger.error("PRIVATE_KEY not set! Check your .env file.")
        sys.exit(1)
    if not config.wallet_address:
        logger.error("WALLET_ADDRESS not set! Check your .env file.")
        sys.exit(1)

    bot = SniperBot(config)

    try:
        asyncio.run(bot.start())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.critical("Fatal error: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
