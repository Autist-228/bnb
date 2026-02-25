"""Pump.fun event definitions and binary parsing."""

import hashlib
import struct
import base64
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("sniper.events")

# Anchor event discriminators: sha256("event:<EventName>")[:8]
CREATE_DISCRIMINATOR = hashlib.sha256(b"event:CreateEvent").digest()[:8]
TRADE_DISCRIMINATOR = hashlib.sha256(b"event:TradeEvent").digest()[:8]
COMPLETE_DISCRIMINATOR = hashlib.sha256(b"event:CompleteEvent").digest()[:8]


@dataclass
class CreateEvent:
    name: str
    symbol: str
    uri: str
    mint: str
    bonding_curve: str
    user: str


@dataclass
class TradeEvent:
    mint: str
    sol_amount: int  # lamports
    token_amount: int
    is_buy: bool
    user: str
    timestamp: int
    virtual_sol_reserves: int  # lamports
    virtual_token_reserves: int
    real_sol_reserves: int  # lamports
    real_token_reserves: int

    @property
    def sol_amount_f(self) -> float:
        return self.sol_amount / 1_000_000_000

    @property
    def price_sol(self) -> float:
        if self.virtual_token_reserves == 0:
            return 0.0
        return self.virtual_sol_reserves / self.virtual_token_reserves

    @property
    def curve_progress_pct(self) -> float:
        threshold_lamports = 85 * 1_000_000_000
        return min(100.0, (self.real_sol_reserves / threshold_lamports) * 100)


@dataclass
class CompleteEvent:
    user: str
    mint: str
    bonding_curve: str
    timestamp: int


def _read_pubkey(data: bytes, offset: int) -> tuple[str, int]:
    """Read 32-byte pubkey, return as base58 string."""
    import base58 as b58
    key_bytes = data[offset:offset + 32]
    return b58.b58encode(key_bytes).decode("ascii"), offset + 32


def _read_string(data: bytes, offset: int) -> tuple[str, int]:
    """Read Borsh string: 4-byte LE length + UTF-8."""
    length = struct.unpack_from("<I", data, offset)[0]
    offset += 4
    text = data[offset:offset + length].decode("utf-8", errors="replace")
    return text, offset + length


def _read_u64(data: bytes, offset: int) -> tuple[int, int]:
    val = struct.unpack_from("<Q", data, offset)[0]
    return val, offset + 8


def _read_i64(data: bytes, offset: int) -> tuple[int, int]:
    val = struct.unpack_from("<q", data, offset)[0]
    return val, offset + 8


def _read_bool(data: bytes, offset: int) -> tuple[bool, int]:
    val = data[offset] != 0
    return val, offset + 1


def parse_create_event(data: bytes) -> Optional[CreateEvent]:
    """Parse CreateEvent from Anchor event data (after discriminator)."""
    try:
        offset = 8  # skip discriminator
        name, offset = _read_string(data, offset)
        symbol, offset = _read_string(data, offset)
        uri, offset = _read_string(data, offset)
        mint, offset = _read_pubkey(data, offset)
        bonding_curve, offset = _read_pubkey(data, offset)
        user, offset = _read_pubkey(data, offset)
        return CreateEvent(
            name=name, symbol=symbol, uri=uri,
            mint=mint, bonding_curve=bonding_curve, user=user,
        )
    except Exception as e:
        logger.debug("Failed to parse CreateEvent: %s", e)
        return None


def parse_trade_event(data: bytes) -> Optional[TradeEvent]:
    """Parse TradeEvent from Anchor event data (after discriminator)."""
    try:
        offset = 8
        mint, offset = _read_pubkey(data, offset)
        sol_amount, offset = _read_u64(data, offset)
        token_amount, offset = _read_u64(data, offset)
        is_buy, offset = _read_bool(data, offset)
        user, offset = _read_pubkey(data, offset)
        timestamp, offset = _read_i64(data, offset)
        virtual_sol_reserves, offset = _read_u64(data, offset)
        virtual_token_reserves, offset = _read_u64(data, offset)
        real_sol_reserves, offset = _read_u64(data, offset)
        real_token_reserves, offset = _read_u64(data, offset)
        return TradeEvent(
            mint=mint, sol_amount=sol_amount, token_amount=token_amount,
            is_buy=is_buy, user=user, timestamp=timestamp,
            virtual_sol_reserves=virtual_sol_reserves,
            virtual_token_reserves=virtual_token_reserves,
            real_sol_reserves=real_sol_reserves,
            real_token_reserves=real_token_reserves,
        )
    except Exception as e:
        logger.debug("Failed to parse TradeEvent: %s", e)
        return None


def parse_complete_event(data: bytes) -> Optional[CompleteEvent]:
    """Parse CompleteEvent from Anchor event data (after discriminator)."""
    try:
        offset = 8
        user, offset = _read_pubkey(data, offset)
        mint, offset = _read_pubkey(data, offset)
        bonding_curve, offset = _read_pubkey(data, offset)
        timestamp, offset = _read_i64(data, offset)
        return CompleteEvent(
            user=user, mint=mint,
            bonding_curve=bonding_curve, timestamp=timestamp,
        )
    except Exception as e:
        logger.debug("Failed to parse CompleteEvent: %s", e)
        return None


def parse_program_data(b64_data: str) -> Optional[CreateEvent | TradeEvent | CompleteEvent]:
    """Parse a 'Program data:' log entry into a typed event."""
    try:
        data = base64.b64decode(b64_data)
    except Exception:
        return None

    if len(data) < 8:
        return None

    disc = data[:8]
    if disc == TRADE_DISCRIMINATOR:
        return parse_trade_event(data)
    elif disc == CREATE_DISCRIMINATOR:
        return parse_create_event(data)
    elif disc == COMPLETE_DISCRIMINATOR:
        return parse_complete_event(data)
    return None
