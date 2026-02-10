import asyncio
import logging
import time
from typing import Optional

from web3 import AsyncWeb3, AsyncHTTPProvider
from web3.middleware import ExtraDataToPOAMiddleware

from src.config import BotConfig

logger = logging.getLogger("sniper.blockchain")


class BlockchainConnection:
    def __init__(self, config: BotConfig):
        self.config = config
        self._w3: Optional[AsyncWeb3] = None
        self._connected = False

    async def connect(self) -> AsyncWeb3:
        logger.info("Connecting to BSC node: %s", self.config.bsc_https_url)
        self._w3 = AsyncWeb3(AsyncHTTPProvider(self.config.bsc_https_url))
        self._w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

        connected = await self._w3.is_connected()
        if not connected:
            raise ConnectionError("Failed to connect to BSC node")

        chain_id = await self._w3.eth.chain_id
        block = await self._w3.eth.block_number
        logger.info("Connected to BSC | Chain ID: %d | Block: %d", chain_id, block)
        self._connected = True
        return self._w3

    @property
    def w3(self) -> AsyncWeb3:
        if self._w3 is None:
            raise RuntimeError("Not connected. Call connect() first.")
        return self._w3

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def get_balance(self, address: str) -> float:
        balance_wei = await self.w3.eth.get_balance(
            self.w3.to_checksum_address(address)
        )
        return float(self.w3.from_wei(balance_wei, "ether"))

    async def get_nonce(self, address: str) -> int:
        return await self.w3.eth.get_transaction_count(
            self.w3.to_checksum_address(address)
        )

    async def get_gas_price(self) -> int:
        if self.config.gas_price_gwei > 0:
            return self.w3.to_wei(self.config.gas_price_gwei, "gwei")
        return await self.w3.eth.gas_price

    async def send_transaction(self, tx: dict) -> str:
        signed = self.w3.eth.account.sign_transaction(tx, self.config.private_key)
        tx_hash = await self.w3.eth.send_raw_transaction(signed.raw_transaction)
        logger.info("TX sent: %s", tx_hash.hex())
        return tx_hash.hex()

    async def wait_for_receipt(self, tx_hash: str, timeout: int = 60) -> dict:
        start = time.time()
        while time.time() - start < timeout:
            try:
                receipt = await self.w3.eth.get_transaction_receipt(tx_hash)
                if receipt is not None:
                    return receipt
            except Exception:
                pass
            await asyncio.sleep(0.5)
        raise TimeoutError(f"TX {tx_hash} not confirmed in {timeout}s")

    async def get_block_number(self) -> int:
        return await self.w3.eth.block_number

    async def estimate_gas(self, tx: dict) -> int:
        try:
            return await self.w3.eth.estimate_gas(tx)
        except Exception as e:
            logger.warning("Gas estimation failed: %s, using default", e)
            return self.config.gas_limit
