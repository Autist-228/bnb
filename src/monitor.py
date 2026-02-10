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
        last_pair_count = await self._safe_pair_count()
        if last_pair_count is None:
            logger.error("Cannot get initial pair count")
            return
        logger.info("Initial pair count: %d | Polling every %.0fs", last_pair_count, poll_sec)

        while self._running:
            await asyncio.sleep(poll_sec)
            try:
                current_count = await self._safe_pair_count()
                if current_count is None:
                    self._rotate_node()
                    continue

                if current_count > last_pair_count:
                    new_count = current_count - last_pair_count
                    logger.info("Detected %d new pair(s) (total: %d)", new_count, current_count)
                    for idx in range(last_pair_count, current_count):
                        await self._process_pair_by_index(idx)
                    last_pair_count = current_count
                else:
                    last_pair_count = current_count
            except Exception as e:
                logger.error("Poll error: %s", e)
                self._rotate_node()

    async def _safe_pair_count(self) -> int | None:
        for _ in range(3):
            try:
                return await self._factory.functions.allPairsLength().call()
            except Exception:
                self._rotate_node()
                await asyncio.sleep(2)
        return None

    async def _process_pair_by_index(self, index: int):
        try:
            pair_address = await self._factory.functions.allPairs(index).call()
            pair_address = self.w3.to_checksum_address(pair_address)

            pair_abi = [
                {"constant": True, "inputs": [], "name": "token0", "outputs": [{"name": "", "type": "address"}], "type": "function"},
                {"constant": True, "inputs": [], "name": "token1", "outputs": [{"name": "", "type": "address"}], "type": "function"},
            ]
            pair_contract = self.w3.eth.contract(address=pair_address, abi=pair_abi)

            token0, token1 = await asyncio.gather(
                pair_contract.functions.token0().call(),
                pair_contract.functions.token1().call(),
            )
            token0 = self.w3.to_checksum_address(token0)
            token1 = self.w3.to_checksum_address(token1)

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

            token_info = await self._fetch_token_info_simple(
                target_token, pair_address, quote_token
            )
            if token_info:
                logger.info(
                    "NEW PAIR: %s (%s) | Pair: %s",
                    token_info.symbol, token_info.address, token_info.pair_address,
                )
                if self.on_new_pair:
                    await self.on_new_pair(token_info)
        except Exception as e:
            logger.error("Process pair index %d error: %s", index, e)

    async def _fetch_token_info_simple(
        self, token_address: str, pair_address: str, quote_token: str,
    ) -> TokenInfo | None:
        try:
            token_contract = self.w3.eth.contract(
                address=self.w3.to_checksum_address(token_address), abi=ERC20_ABI,
            )
            name, symbol, decimals, total_supply = await asyncio.gather(
                self._safe_call(token_contract.functions.name(), "Unknown"),
                self._safe_call(token_contract.functions.symbol(), "???"),
                self._safe_call(token_contract.functions.decimals(), 18),
                self._safe_call(token_contract.functions.totalSupply(), 0),
            )
            return TokenInfo(
                address=token_address, pair_address=pair_address,
                name=name, symbol=symbol, decimals=decimals,
                total_supply=total_supply, quote_token=quote_token,
                block_number=0, timestamp=time.time(),
            )
        except Exception as e:
            logger.error("Fetch token info error for %s: %s", token_address, e)
            return None

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
