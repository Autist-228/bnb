"""Utility functions."""

import logging
import sys
from colorama import Fore, Style, init

init(autoreset=True)


class ColoredFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG: Fore.CYAN,
        logging.INFO: Fore.GREEN,
        logging.WARNING: Fore.YELLOW,
        logging.ERROR: Fore.RED,
        logging.CRITICAL: Fore.MAGENTA,
    }

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelno, "")
        # Color the tag/name
        name = record.name.split(".")[-1].upper()
        timestamp = self.formatTime(record, "%H:%M:%S")
        msg = record.getMessage()
        return f"{Fore.WHITE}{timestamp}{Style.RESET_ALL} [{color}{name}{Style.RESET_ALL}] {msg}"


def setup_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(ColoredFormatter())
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)
    # Suppress noisy websocket client debug logs
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("websockets.client").setLevel(logging.WARNING)


def sol_to_lamports(sol: float) -> int:
    return int(sol * 1_000_000_000)


def lamports_to_sol(lamports: int) -> float:
    return lamports / 1_000_000_000


def format_sol(sol: float) -> str:
    return f"{sol:.6f} SOL"


def format_usd(usd: float) -> str:
    return f"${usd:.2f}"


def short_addr(addr: str) -> str:
    if len(addr) <= 10:
        return addr
    return f"{addr[:4]}..{addr[-4:]}"
