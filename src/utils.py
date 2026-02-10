import logging
import sys
from datetime import datetime

from colorama import Fore, Style, init

init(autoreset=True)


class ColoredFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG: Fore.CYAN,
        logging.INFO: Fore.GREEN,
        logging.WARNING: Fore.YELLOW,
        logging.ERROR: Fore.RED,
        logging.CRITICAL: Fore.RED + Style.BRIGHT,
    }

    KEYWORDS = {
        "[BUY SIGNAL]": Fore.GREEN + Style.BRIGHT,
        "[BOUGHT]": Fore.GREEN + Style.BRIGHT,
        "[SOLD]": Fore.CYAN + Style.BRIGHT,
        "[AUTO-SELL]": Fore.CYAN + Style.BRIGHT,
        "[SKIP]": Fore.YELLOW,
        "[PASS]": Fore.GREEN,
        "[ANALYZE]": Fore.BLUE,
        "[BUY FAILED]": Fore.RED + Style.BRIGHT,
        "HONEYPOT": Fore.RED + Style.BRIGHT,
        "NEW PAIR": Fore.MAGENTA + Style.BRIGHT,
    }

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelno, "")
        timestamp = datetime.fromtimestamp(record.created).strftime("%H:%M:%S.%f")[:-3]

        msg = record.getMessage()
        for keyword, kw_color in self.KEYWORDS.items():
            if keyword in msg:
                msg = msg.replace(keyword, f"{kw_color}{keyword}{Style.RESET_ALL}")
                break

        return (
            f"{Fore.WHITE}{timestamp}{Style.RESET_ALL} "
            f"{color}{record.levelname:<8}{Style.RESET_ALL} "
            f"{Fore.BLUE}{record.name:<25}{Style.RESET_ALL} "
            f"{msg}"
        )


def setup_logging(level: int = logging.INFO):
    root = logging.getLogger()
    root.setLevel(level)

    for handler in root.handlers[:]:
        root.removeHandler(handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(ColoredFormatter())
    root.addHandler(console_handler)

    logging.getLogger("web3").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)


def format_bnb(amount: float) -> str:
    return f"{amount:.4f} BNB"


def format_percentage(value: float) -> str:
    return f"{value:.2f}%"


def short_address(address: str) -> str:
    if len(address) < 10:
        return address
    return f"{address[:6]}...{address[-4:]}"
