"""Track all pump.fun tokens and their state."""

import time
import logging
from dataclasses import dataclass, field
from typing import Optional

from src.events import CreateEvent, TradeEvent, CompleteEvent

logger = logging.getLogger("sniper.tracker")


@dataclass
class TradeRecord:
    timestamp: float
    sol_amount: float  # SOL
    is_buy: bool
    user: str


@dataclass
class TokenInfo:
    mint: str
    name: str = ""
    symbol: str = ""
    uri: str = ""
    bonding_curve: str = ""
    creator: str = ""
    created_at: float = 0.0

    # Bonding curve state (from latest TradeEvent)
    virtual_sol_reserves: int = 0
    virtual_token_reserves: int = 0
    real_sol_reserves: int = 0
    real_token_reserves: int = 0

    # Tracking
    unique_buyers: set = field(default_factory=set)
    unique_sellers: set = field(default_factory=set)
    trade_history: list[TradeRecord] = field(default_factory=list)
    total_buy_sol: float = 0.0
    total_sell_sol: float = 0.0
    total_buys: int = 0
    total_sells: int = 0
    is_graduated: bool = False
    graduated_at: float = 0.0
    last_update: float = 0.0

    @property
    def curve_progress_pct(self) -> float:
        threshold_lamports = 85 * 1_000_000_000
        if threshold_lamports == 0:
            return 0.0
        return min(100.0, (self.real_sol_reserves / threshold_lamports) * 100)

    @property
    def price_sol(self) -> float:
        if self.virtual_token_reserves == 0:
            return 0.0
        return self.virtual_sol_reserves / self.virtual_token_reserves

    @property
    def price_sol_human(self) -> float:
        """Price in SOL per token (human-readable with 6 decimals for pump.fun tokens)."""
        raw = self.price_sol
        # virtual reserves are in lamports and raw token units
        # price_sol = lamports_per_token / 1e9 to get SOL per token
        return raw / 1_000_000_000

    def velocity_sol(self, window_seconds: int = 60) -> float:
        """SOL bought in the last N seconds."""
        cutoff = time.time() - window_seconds
        total = 0.0
        for trade in reversed(self.trade_history):
            if trade.timestamp < cutoff:
                break
            if trade.is_buy:
                total += trade.sol_amount
        return total

    def velocity_spike(self, window: int = 60, lookback: int = 300) -> float:
        """Ratio of recent velocity to average velocity over longer period."""
        recent = self.velocity_sol(window)
        if lookback <= window:
            return 0.0
        older_total = 0.0
        older_count = 0
        now = time.time()
        for trade in self.trade_history:
            age = now - trade.timestamp
            if age > lookback:
                continue
            if age > window and trade.is_buy:
                older_total += trade.sol_amount
                older_count += 1
        avg_period = (lookback - window) / window
        if avg_period <= 0:
            return 0.0
        avg_velocity = older_total / avg_period if avg_period > 0 else 0.0
        if avg_velocity <= 0:
            # No older data to compare - return high but finite ratio
            return 10.0 if recent > 0 else 0.0
        return recent / avg_velocity


class TokenTracker:
    """Manages state of all tracked pump.fun tokens."""

    def __init__(self):
        self.tokens: dict[str, TokenInfo] = {}
        self.total_creates: int = 0
        self.total_trades: int = 0
        self.total_graduations: int = 0

    def handle_create(self, event: CreateEvent) -> TokenInfo:
        self.total_creates += 1
        token = TokenInfo(
            mint=event.mint,
            name=event.name,
            symbol=event.symbol,
            uri=event.uri,
            bonding_curve=event.bonding_curve,
            creator=event.user,
            created_at=time.time(),
            last_update=time.time(),
        )
        self.tokens[event.mint] = token
        logger.debug("New token: $%s (%s) by %s", event.symbol, event.mint[:8], event.user[:8])
        return token

    def handle_trade(self, event: TradeEvent) -> Optional[TokenInfo]:
        self.total_trades += 1
        token = self.tokens.get(event.mint)
        if token is None:
            # Token was created before we started listening
            token = TokenInfo(
                mint=event.mint,
                created_at=time.time(),
                last_update=time.time(),
            )
            self.tokens[event.mint] = token

        # Update bonding curve state
        token.virtual_sol_reserves = event.virtual_sol_reserves
        token.virtual_token_reserves = event.virtual_token_reserves
        token.real_sol_reserves = event.real_sol_reserves
        token.real_token_reserves = event.real_token_reserves
        token.last_update = time.time()

        sol_amount = event.sol_amount / 1_000_000_000

        record = TradeRecord(
            timestamp=time.time(),
            sol_amount=sol_amount,
            is_buy=event.is_buy,
            user=event.user,
        )
        token.trade_history.append(record)

        if event.is_buy:
            token.unique_buyers.add(event.user)
            token.total_buy_sol += sol_amount
            token.total_buys += 1
        else:
            token.unique_sellers.add(event.user)
            token.total_sell_sol += sol_amount
            token.total_sells += 1

        return token

    def handle_complete(self, event: CompleteEvent) -> Optional[TokenInfo]:
        self.total_graduations += 1
        token = self.tokens.get(event.mint)
        if token is None:
            token = TokenInfo(mint=event.mint, last_update=time.time())
            self.tokens[event.mint] = token

        token.is_graduated = True
        token.graduated_at = time.time()
        token.last_update = time.time()
        logger.info("GRADUATION: %s ($%s)", event.mint[:8], token.symbol or "???")
        return token

    def get_token(self, mint: str) -> Optional[TokenInfo]:
        return self.tokens.get(mint)

    def active_count(self) -> int:
        return len(self.tokens)
