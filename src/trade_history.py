import csv
import logging
import os
import time
from dataclasses import dataclass, asdict
from typing import Optional

import numpy as np

from src.ml_model import FEATURE_NAMES

logger = logging.getLogger("sniper.history")

HISTORY_COLUMNS = FEATURE_NAMES + [
    "token_address",
    "pair_address",
    "symbol",
    "buy_price_bnb",
    "buy_price_usd",
    "sell_price_bnb",
    "sell_price_usd",
    "profit_pct",
    "profitable",
    "buy_tx",
    "sell_tx",
    "buy_timestamp",
    "sell_timestamp",
    "status",
]


@dataclass
class TradeRecord:
    is_not_honeypot: float = 0.0
    buy_tax: float = 0.0
    sell_tax: float = 0.0
    ownership_renounced: float = 0.0
    no_proxy: float = 0.0
    holder_count: float = 0.0
    top_holder_pct: float = 0.0
    not_mintable: float = 0.0
    liquidity_locked: float = 0.0
    liquidity_usd: float = 0.0
    token_age_seconds: float = 0.0
    price_impact_pct: float = 0.0

    token_address: str = ""
    pair_address: str = ""
    symbol: str = ""
    buy_price_bnb: float = 0.0
    buy_price_usd: float = 0.0
    sell_price_bnb: float = 0.0
    sell_price_usd: float = 0.0
    profit_pct: float = 0.0
    profitable: int = 0
    buy_tx: str = ""
    sell_tx: str = ""
    buy_timestamp: float = 0.0
    sell_timestamp: float = 0.0
    status: str = "open"


class TradeHistory:
    def __init__(self, filepath: str):
        self.filepath = filepath
        self._records: list[TradeRecord] = []
        self._open_trades: dict[str, TradeRecord] = {}
        self._load()

    def _load(self):
        if not os.path.exists(self.filepath):
            os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
            self._write_header()
            logger.info("Created new trade history: %s", self.filepath)
            return

        try:
            with open(self.filepath, "r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    record = self._row_to_record(row)
                    self._records.append(record)
                    if record.status == "open":
                        self._open_trades[record.token_address] = record

            logger.info(
                "Loaded %d trades (%d open) from %s",
                len(self._records),
                len(self._open_trades),
                self.filepath,
            )
        except Exception as e:
            logger.error("Failed to load trade history: %s", e)
            self._write_header()

    def _write_header(self):
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        with open(self.filepath, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(HISTORY_COLUMNS)

    @staticmethod
    def _row_to_record(row: dict) -> TradeRecord:
        return TradeRecord(
            is_not_honeypot=float(row.get("is_not_honeypot", 0)),
            buy_tax=float(row.get("buy_tax", 0)),
            sell_tax=float(row.get("sell_tax", 0)),
            ownership_renounced=float(row.get("ownership_renounced", 0)),
            no_proxy=float(row.get("no_proxy", 0)),
            holder_count=float(row.get("holder_count", 0)),
            top_holder_pct=float(row.get("top_holder_pct", 0)),
            not_mintable=float(row.get("not_mintable", 0)),
            liquidity_locked=float(row.get("liquidity_locked", 0)),
            liquidity_usd=float(row.get("liquidity_usd", 0)),
            token_age_seconds=float(row.get("token_age_seconds", 0)),
            price_impact_pct=float(row.get("price_impact_pct", 0)),
            token_address=row.get("token_address", ""),
            pair_address=row.get("pair_address", ""),
            symbol=row.get("symbol", ""),
            buy_price_bnb=float(row.get("buy_price_bnb", 0)),
            buy_price_usd=float(row.get("buy_price_usd", 0)),
            sell_price_bnb=float(row.get("sell_price_bnb", 0)),
            sell_price_usd=float(row.get("sell_price_usd", 0)),
            profit_pct=float(row.get("profit_pct", 0)),
            profitable=int(float(row.get("profitable", 0))),
            buy_tx=row.get("buy_tx", ""),
            sell_tx=row.get("sell_tx", ""),
            buy_timestamp=float(row.get("buy_timestamp", 0)),
            sell_timestamp=float(row.get("sell_timestamp", 0)),
            status=row.get("status", "open"),
        )

    def record_buy(
        self,
        features: list[float],
        token_address: str,
        pair_address: str,
        symbol: str,
        buy_price_bnb: float,
        buy_price_usd: float,
        buy_tx: str,
    ) -> TradeRecord:
        record = TradeRecord(
            is_not_honeypot=features[0],
            buy_tax=features[1],
            sell_tax=features[2],
            ownership_renounced=features[3],
            no_proxy=features[4],
            holder_count=features[5],
            top_holder_pct=features[6],
            not_mintable=features[7],
            liquidity_locked=features[8],
            liquidity_usd=features[9],
            token_age_seconds=features[10],
            price_impact_pct=features[11],
            token_address=token_address,
            pair_address=pair_address,
            symbol=symbol,
            buy_price_bnb=buy_price_bnb,
            buy_price_usd=buy_price_usd,
            buy_tx=buy_tx,
            buy_timestamp=time.time(),
            status="open",
        )

        self._records.append(record)
        self._open_trades[token_address] = record
        self._append_row(record)

        logger.info(
            "[HISTORY] BUY recorded: %s | $%.2f | TX: %s",
            symbol,
            buy_price_usd,
            buy_tx[:16] + "...",
        )
        return record

    def record_sell(
        self,
        token_address: str,
        sell_price_bnb: float,
        sell_price_usd: float,
        sell_tx: str,
        profit_pct: float,
    ) -> Optional[TradeRecord]:
        record = self._open_trades.pop(token_address, None)
        if record is None:
            logger.warning("No open trade for %s", token_address)
            return None

        record.sell_price_bnb = sell_price_bnb
        record.sell_price_usd = sell_price_usd
        record.sell_tx = sell_tx
        record.sell_timestamp = time.time()
        record.profit_pct = profit_pct
        record.profitable = 1 if profit_pct > 0 else 0
        record.status = "closed"

        self._rewrite_all()

        logger.info(
            "[HISTORY] SELL recorded: %s | Profit: %.2f%% | %s",
            record.symbol,
            profit_pct,
            "WIN" if record.profitable else "LOSS",
        )
        return record

    def _append_row(self, record: TradeRecord):
        try:
            with open(self.filepath, "a", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(self._record_to_row(record))
        except Exception as e:
            logger.error("Failed to write trade record: %s", e)

    def _rewrite_all(self):
        try:
            with open(self.filepath, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(HISTORY_COLUMNS)
                for rec in self._records:
                    writer.writerow(self._record_to_row(rec))
        except Exception as e:
            logger.error("Failed to rewrite trade history: %s", e)

    @staticmethod
    def _record_to_row(record: TradeRecord) -> list:
        d = asdict(record)
        return [d[col] for col in HISTORY_COLUMNS]

    def get_closed_trades(self) -> list[TradeRecord]:
        return [r for r in self._records if r.status == "closed"]

    def get_training_data(self) -> Optional[tuple[np.ndarray, np.ndarray]]:
        closed = self.get_closed_trades()
        if len(closed) < 10:
            return None

        X = []
        y = []
        for rec in closed:
            X.append([
                rec.is_not_honeypot,
                rec.buy_tax,
                rec.sell_tax,
                rec.ownership_renounced,
                rec.no_proxy,
                rec.holder_count,
                rec.top_holder_pct,
                rec.not_mintable,
                rec.liquidity_locked,
                rec.liquidity_usd,
                rec.token_age_seconds,
                rec.price_impact_pct,
            ])
            y.append(float(rec.profitable))

        return np.array(X), np.array(y)

    @property
    def total_trades(self) -> int:
        return len(self._records)

    @property
    def closed_trades_count(self) -> int:
        return len(self.get_closed_trades())

    @property
    def open_trades(self) -> dict[str, TradeRecord]:
        return self._open_trades

    def get_stats(self) -> dict:
        closed = self.get_closed_trades()
        if not closed:
            return {
                "total": 0, "wins": 0, "losses": 0,
                "win_rate": 0.0, "avg_profit": 0.0,
            }

        wins = [t for t in closed if t.profitable]
        losses = [t for t in closed if not t.profitable]
        avg_profit = sum(t.profit_pct for t in closed) / len(closed)

        return {
            "total": len(closed),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / len(closed) * 100,
            "avg_profit": avg_profit,
        }
