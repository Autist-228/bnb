import asyncio
import logging
import time
from typing import Optional

from src.config import BotConfig
from src.blockchain import BlockchainConnection
from src.monitor import PairMonitor, TokenInfo
from src.liquidity import LiquidityChecker
from src.safety import SafetyAnalyzer
from src.ml_model import TokenScorer
from src.sniper import SniperExecutor
from src.trade_history import TradeHistory

logger = logging.getLogger("sniper.bot")


class SniperBot:
    def __init__(self, config: BotConfig):
        self.config = config
        self.connection = BlockchainConnection(config)
        self.liquidity_checker: Optional[LiquidityChecker] = None
        self.safety_analyzer: Optional[SafetyAnalyzer] = None
        self.ml_scorer = TokenScorer()
        self.executor: Optional[SniperExecutor] = None
        self.monitor: Optional[PairMonitor] = None
        self.trade_history = TradeHistory(config.trade_history_path)
        self._last_retrain_count = 0

        self._stats = {
            "tokens_seen": 0,
            "tokens_analyzed": 0,
            "tokens_passed_liquidity": 0,
            "tokens_passed_safety": 0,
            "tokens_passed_ml": 0,
            "buys_attempted": 0,
            "buys_success": 0,
            "sells_attempted": 0,
            "sells_success": 0,
            "start_time": 0.0,
        }
        self._running = False
        self._processing_lock = asyncio.Lock()

    async def start(self):
        logger.info("=" * 60)
        logger.info("BNB SNIPER BOT - PancakeSwap V2 + ML")
        logger.info("=" * 60)

        w3 = await self.connection.connect()

        balance = await self.connection.get_balance(self.config.wallet_address)
        logger.info("Wallet: %s | Balance: %.4f BNB", self.config.wallet_address, balance)

        if balance < self.config.buy_amount_bnb:
            logger.error(
                "Insufficient balance: %.4f BNB < %.4f BNB (buy amount)",
                balance,
                self.config.buy_amount_bnb,
            )
            return

        self.liquidity_checker = LiquidityChecker(w3, self.config)
        self.safety_analyzer = SafetyAnalyzer(w3, self.config)
        self.executor = SniperExecutor(self.connection, self.config)

        logger.info("Loading ML model...")
        self.ml_scorer.load()
        importance = self.ml_scorer.get_feature_importance()
        if importance:
            top_features = sorted(importance.items(), key=lambda x: x[1], reverse=True)[:5]
            logger.info("Top ML features: %s", top_features)

        trade_stats = self.trade_history.get_stats()
        if trade_stats["total"] > 0:
            logger.info(
                "Trade history: %d trades | Win rate: %.1f%% | Avg profit: %.2f%%",
                trade_stats["total"],
                trade_stats["win_rate"],
                trade_stats["avg_profit"],
            )
            self._try_retrain()

        logger.info("Configuration:")
        logger.info("  Buy amount: %.4f BNB", self.config.buy_amount_bnb)
        logger.info("  Min liquidity: $%.0f", self.config.min_liquidity_usd)
        logger.info("  Max buy tax: %.1f%%", self.config.max_buy_tax)
        logger.info("  Max sell tax: %.1f%%", self.config.max_sell_tax)
        logger.info("  Slippage: %.1f%%", self.config.slippage_percent)
        logger.info("  ML min score: %.2f", self.config.ml_min_score)
        logger.info("  Take profit: %.0f%%", self.config.take_profit_percent)
        logger.info("  Stop loss: %.0f%%", self.config.stop_loss_percent)
        logger.info("  Poll interval: %dms", self.config.poll_interval_ms)
        logger.info("  Auto-retrain every: %d closed trades", self.config.auto_retrain_every)

        self._stats["start_time"] = time.time()
        self._running = True

        self.monitor = PairMonitor(
            w3=w3,
            config=self.config,
            on_new_pair=self._on_new_pair,
        )

        position_task = asyncio.create_task(self._position_monitor_loop())

        try:
            logger.info("Starting pair monitor...")
            await self.monitor.start()
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            self._running = False
            position_task.cancel()
            if self.monitor:
                await self.monitor.stop()
            self._print_stats()

    async def _on_new_pair(self, token: TokenInfo):
        self._stats["tokens_seen"] += 1

        async with self._processing_lock:
            try:
                await self._process_token(token)
            except Exception as e:
                logger.error("Error processing %s: %s", token.symbol, e)

    async def _process_token(self, token: TokenInfo):
        start_time = time.time()
        self._stats["tokens_analyzed"] += 1

        logger.info(
            "[ANALYZE] %s (%s) | Pair: %s",
            token.symbol,
            token.address[:16] + "...",
            token.pair_address[:16] + "...",
        )

        meets_liq, liq_info = await self.liquidity_checker.meets_minimum(
            token.pair_address,
            token.address,
            token.quote_token,
            token.decimals,
        )

        if not meets_liq:
            logger.info("[SKIP] %s - Liquidity too low", token.symbol)
            return

        self._stats["tokens_passed_liquidity"] += 1
        liquidity_usd = liq_info.quote_reserve_usd
        liquidity_bnb = liq_info.quote_reserve_bnb
        logger.info(
            "[PASS] %s - Liquidity: $%.0f (%.2f BNB)",
            token.symbol, liquidity_usd, liquidity_bnb,
        )

        safety = await self.safety_analyzer.analyze(
            token.address,
            token.pair_address,
            token.quote_token,
        )

        if safety.is_honeypot:
            logger.info("[SKIP] %s - HONEYPOT detected", token.symbol)
            return

        if safety.buy_tax > self.config.max_buy_tax:
            logger.info(
                "[SKIP] %s - Buy tax too high: %.1f%%",
                token.symbol,
                safety.buy_tax,
            )
            return

        if safety.sell_tax > self.config.max_sell_tax:
            logger.info(
                "[SKIP] %s - Sell tax too high: %.1f%%",
                token.symbol,
                safety.sell_tax,
            )
            return

        self._stats["tokens_passed_safety"] += 1

        token_age = time.time() - token.timestamp
        price_impact = self._estimate_price_impact(
            self.config.buy_amount_bnb, liquidity_bnb
        )

        ml_score, ml_approved, features = self.ml_scorer.predict(
            safety=safety,
            liquidity_usd=liquidity_usd,
            token_age_seconds=token_age,
            price_impact_pct=price_impact,
        )

        if ml_score < self.config.ml_min_score:
            logger.info(
                "[SKIP] %s - ML score too low: %.3f (min: %.2f)",
                token.symbol,
                ml_score,
                self.config.ml_min_score,
            )
            return

        self._stats["tokens_passed_ml"] += 1

        elapsed = time.time() - start_time
        logger.info(
            "[BUY SIGNAL] %s | Score: %.3f | Liq: $%.0f | "
            "Tax: %.1f%%/%.1f%% | Analysis: %.2fs",
            token.symbol,
            ml_score,
            liquidity_usd,
            safety.buy_tax,
            safety.sell_tax,
            elapsed,
        )

        self._stats["buys_attempted"] += 1
        result = await self.executor.buy_token(
            token_address=token.address,
            amount_bnb=self.config.buy_amount_bnb,
        )

        if result["success"]:
            self._stats["buys_success"] += 1

            bnb_price = await self.liquidity_checker.get_bnb_price_usd()
            buy_price_usd = self.config.buy_amount_bnb * bnb_price

            self.trade_history.record_buy(
                features=features,
                token_address=token.address,
                pair_address=token.pair_address,
                symbol=token.symbol,
                buy_price_bnb=self.config.buy_amount_bnb,
                buy_price_usd=buy_price_usd,
                buy_tx=result["tx_hash"],
            )

            logger.info(
                "[BOUGHT] %s | TX: %s | $%.2f | Gas: %d",
                token.symbol,
                result["tx_hash"],
                buy_price_usd,
                result["gas_used"],
            )
        else:
            logger.error("[BUY FAILED] %s | TX: %s", token.symbol, result["tx_hash"])

    async def _position_monitor_loop(self):
        while self._running:
            try:
                await asyncio.sleep(5)

                if not self.executor:
                    continue

                positions = dict(self.executor.active_positions)
                for token_address in positions:
                    profit_info = await self.executor.check_profit(token_address)

                    if profit_info["should_sell"]:
                        reason = profit_info["reason"]
                        profit_pct = profit_info["profit_pct"]
                        logger.info(
                            "[AUTO-SELL] %s | Reason: %s | Profit: %.2f%%",
                            token_address[:16] + "...",
                            reason,
                            profit_pct,
                        )

                        self._stats["sells_attempted"] += 1
                        result = await self.executor.sell_token(token_address)
                        if result["success"]:
                            self._stats["sells_success"] += 1

                            bnb_price = await self.liquidity_checker.get_bnb_price_usd()
                            sell_value_bnb = profit_info.get("current_value_bnb", 0)
                            sell_value_usd = sell_value_bnb * bnb_price

                            self.trade_history.record_sell(
                                token_address=token_address,
                                sell_price_bnb=sell_value_bnb,
                                sell_price_usd=sell_value_usd,
                                sell_tx=result["tx_hash"],
                                profit_pct=profit_pct,
                            )

                            self._try_retrain()

                            logger.info(
                                "[SOLD] %s | TX: %s | Profit: %.2f%% | $%.2f",
                                token_address[:16] + "...",
                                result["tx_hash"],
                                profit_pct,
                                sell_value_usd,
                            )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Position monitor error: %s", e)

    @staticmethod
    def _estimate_price_impact(buy_amount_bnb: float, liquidity_bnb: float) -> float:
        if liquidity_bnb <= 0:
            return 100.0
        return (buy_amount_bnb / liquidity_bnb) * 100

    def _try_retrain(self):
        closed_count = self.trade_history.closed_trades_count
        if closed_count <= self._last_retrain_count:
            return
        if (closed_count - self._last_retrain_count) < self.config.auto_retrain_every:
            return

        training_data = self.trade_history.get_training_data()
        if training_data is None:
            return

        X, y = training_data
        logger.info(
            "[RETRAIN] Auto-retraining ML model with %d real trades",
            len(X),
        )
        accuracy = self.ml_scorer.retrain(X, y)
        self._last_retrain_count = closed_count

        stats = self.trade_history.get_stats()
        logger.info(
            "[RETRAIN] Model updated | Accuracy: %.3f | "
            "Win rate: %.1f%% | Avg profit: %.2f%%",
            accuracy,
            stats["win_rate"],
            stats["avg_profit"],
        )

    def _print_stats(self):
        elapsed = time.time() - self._stats["start_time"]
        trade_stats = self.trade_history.get_stats()
        logger.info("=" * 60)
        logger.info("SESSION STATS (%.0f seconds)", elapsed)
        logger.info("=" * 60)
        logger.info("Tokens seen:       %d", self._stats["tokens_seen"])
        logger.info("Tokens analyzed:   %d", self._stats["tokens_analyzed"])
        logger.info("Passed liquidity:  %d", self._stats["tokens_passed_liquidity"])
        logger.info("Passed safety:     %d", self._stats["tokens_passed_safety"])
        logger.info("Passed ML:         %d", self._stats["tokens_passed_ml"])
        logger.info("Buys attempted:    %d", self._stats["buys_attempted"])
        logger.info("Buys success:      %d", self._stats["buys_success"])
        logger.info("Sells attempted:   %d", self._stats["sells_attempted"])
        logger.info("Sells success:     %d", self._stats["sells_success"])
        logger.info("-" * 60)
        logger.info("Total trades:      %d", trade_stats["total"])
        logger.info("Win rate:          %.1f%%", trade_stats["win_rate"])
        logger.info("Avg profit:        %.2f%%", trade_stats["avg_profit"])
        logger.info("=" * 60)
