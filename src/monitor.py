import asyncio
import logging
import time
from typing import Callable, Optional

from web3 import AsyncWeb3, AsyncHTTPProvider
from web3.contract import AsyncContract
from web3.middleware import ExtraDataToPOAMiddleware

from src.config import (
    BotConfig,
    BSC_PUBLIC_NODES,
    FACTORY_ABI,
    ERC20_ABI,
)

PAIR_CREATED_TOPIC = "0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9"

logger = logging.getLogger("sniper.monitor")


class TokenInfo:
    def __init__(
        self,
        address: str,
        pair_address: str,
        name: str,
        symbol: str,
        decimals: int,
        total_supply: int,
        quote_token: str,
        block_number: int,
        timestamp: float,
    ):
        self.address = address
        self.pair_address = pair_address
        self.name = name
        self.symbol = symbol
        self.decimals = decimals
        self.total_supply = total_supply
        self.quote_token = quote_token
        self.block_number = block_number
        self.timestamp = timestamp

    def __repr__(self) -> str:
        return (
            f"Token({self.symbol} | {self.address[:10]}... | "
            f"pair={self.pair_address[:10]}...)"
        )


class PairMonitor:
    def __init__(
        self,
        w3: AsyncWeb3,
        config: BotConfig,
        on_new_pair: Optional[Callable] = None,
    ):
        self.w3 = w3
        self.config = config
        self.on_new_pair = on_new_pair
        self._running = False
        self._last_block = 0
        self._seen_pairs: set = set()
        self._factory: Optional[AsyncContract] = None
        self._node_index = 0
        self._rate_limit_count = 0

    async def start(self):
        self._factory = self.w3.eth.contract(
            address=self.w3.to_checksum_address(self.config.pancake_factory),
            abi=FACTORY_ABI,
        )
        self._last_block = await self.w3.eth.block_number
        self._running = True
        logger.info(
            "PairMonitor started | Polling every %dms | From block %d",
            self.config.poll_interval_ms,
            self._last_block,
        )
        await self._poll_loop()

    async def stop(self):
        self._running = False
        logger.info("PairMonitor stopped")

    def _rotate_node(self):
        nodes = BSC_PUBLIC_NODES
        if not nodes:
            return
        self._node_index = (self._node_index + 1) % len(nodes)
        new_url = nodes[self._node_index]
        self.w3 = AsyncWeb3(AsyncHTTPProvider(new_url))
        self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        self._factory = self.w3.eth.contract(
            address=self.w3.to_checksum_address(self.config.pancake_factory),
            abi=FACTORY_ABI,
        )
        logger.info("Switched to BSC node: %s", new_url)

    async def _poll_loop(self):
        poll_sec = max(self.config.poll_interval_ms / 1000.0, 5.0)
        while self._running:
            try:
                current_block = await self.w3.eth.block_number
                if current_block <= self._last_block:
                    await asyncio.sleep(poll_sec)
                    continue

                gap = current_block - self._last_block
                if gap > 100:
                    self._last_block = current_block - 20
                    gap = current_block - self._last_block

                ok = await self._scan_blocks(self._last_block + 1, current_block)
                if ok:
                    self._last_block = current_block
                    self._rate_limit_count = 0
                else:
                    self._rate_limit_count += 1
                    self._rotate_node()
                    self._last_block = current_block
                    await asyncio.sleep(poll_sec * 2)
                    continue
            except Exception as e:
                msg = str(e).lower()
                if any(s in msg for s in ["limit", "32005", "429", "too many"]):
                    self._rotate_node()
                else:
                    logger.error("Poll error: %s", e)
                    self._rotate_node()
                await asyncio.sleep(poll_sec * 2)
                continue

            await asyncio.sleep(poll_sec)

    async def _scan_blocks(self, from_block: int, to_block: int) -> bool:
        try:
            pair_created_filter = {
                "fromBlock": from_block,
                "toBlock": to_block,
                "address": self.w3.to_checksum_address(self.config.pancake_factory),
                "topics": [PAIR_CREATED_TOPIC],
            }
            logs = await self.w3.eth.get_logs(pair_created_filter)

            for log in logs:
                if len(log["topics"]) >= 3:
                    await self._process_pair_event(log)

            return True
        except Exception as e:
            msg = str(e).lower()
            is_rate_limit = any(s in msg for s in ["limit", "32005", "32000", "429", "too many"])
            if is_rate_limit:
                if self._rate_limit_count % 20 == 0:
                    logger.warning("Rate limited on blocks %d-%d", from_block, to_block)
            else:
                logger.error("Block scan error [%d-%d]: %s", from_block, to_block, e)
            return False

    async def _process_pair_event(self, log: dict):
        try:
            token0 = self.w3.to_checksum_address(
                "0x" + log["topics"][1].hex()[-40:]
            )
            token1 = self.w3.to_checksum_address(
                "0x" + log["topics"][2].hex()[-40:]
            )

            pair_key = f"{token0}-{token1}"
            if pair_key in self._seen_pairs:
                return
            self._seen_pairs.add(pair_key)

            quote_tokens_lower = [q.lower() for q in self.config.quote_tokens]

            if token0.lower() in quote_tokens_lower:
                target_token = token1
                quote_token = token0
            elif token1.lower() in quote_tokens_lower:
                target_token = token0
                quote_token = token1
            else:
                return

            pair_address = self._extract_pair_address(log)
            if not pair_address:
                pair_address = await self._get_pair_address(token0, token1)

            token_info = await self._fetch_token_info(
                target_token, pair_address, quote_token, log
            )

            if token_info:
                logger.info(
                    "NEW PAIR: %s (%s) | Pair: %s | Block: %d",
                    token_info.symbol,
                    token_info.address,
                    token_info.pair_address,
                    token_info.block_number,
                )
                if self.on_new_pair:
                    await self.on_new_pair(token_info)

        except Exception as e:
            logger.error("Process pair event error: %s", e)

    def _extract_pair_address(self, log: dict) -> Optional[str]:
        try:
            if log.get("data") and len(log["data"]) >= 66:
                data_hex = log["data"].hex() if isinstance(log["data"], bytes) else log["data"]
                if data_hex.startswith("0x"):
                    data_hex = data_hex[2:]
                addr_hex = data_hex[:64]
                return self.w3.to_checksum_address("0x" + addr_hex[-40:])
        except Exception:
            pass
        return None

    async def _get_pair_address(self, token0: str, token1: str) -> str:
        result = await self._factory.functions.getPair(token0, token1).call()
        return self.w3.to_checksum_address(result)

    async def _fetch_token_info(
        self,
        token_address: str,
        pair_address: str,
        quote_token: str,
        log: dict,
    ) -> Optional[TokenInfo]:
        try:
            token_contract = self.w3.eth.contract(
                address=self.w3.to_checksum_address(token_address),
                abi=ERC20_ABI,
            )

            name, symbol, decimals, total_supply = await asyncio.gather(
                self._safe_call(token_contract.functions.name(), "Unknown"),
                self._safe_call(token_contract.functions.symbol(), "???"),
                self._safe_call(token_contract.functions.decimals(), 18),
                self._safe_call(token_contract.functions.totalSupply(), 0),
            )

            return TokenInfo(
                address=token_address,
                pair_address=pair_address,
                name=name,
                symbol=symbol,
                decimals=decimals,
                total_supply=total_supply,
                quote_token=quote_token,
                block_number=log.get("blockNumber", 0),
                timestamp=time.time(),
            )
        except Exception as e:
            logger.error("Fetch token info error for %s: %s", token_address, e)
            return None

    @staticmethod
    async def _safe_call(func, default):
        try:
            return await func.call()
        except Exception:
            return default
