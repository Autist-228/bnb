import logging
import time

from web3 import AsyncWeb3

from src.config import BotConfig, ROUTER_ABI, ERC20_ABI, WBNB_ADDRESS
from src.blockchain import BlockchainConnection

logger = logging.getLogger("sniper.executor")

MAX_UINT256 = 2**256 - 1


class SniperExecutor:
    def __init__(self, connection: BlockchainConnection, config: BotConfig):
        self.conn = connection
        self.config = config
        self._active_positions: dict[str, dict] = {}

    @property
    def w3(self) -> AsyncWeb3:
        return self.conn.w3

    @property
    def active_positions(self) -> dict:
        return self._active_positions

    async def buy_token(
        self,
        token_address: str,
        amount_bnb: float,
        slippage: float = 0,
    ) -> dict:
        if slippage <= 0:
            slippage = self.config.slippage_percent

        router = self.w3.eth.contract(
            address=self.w3.to_checksum_address(self.config.pancake_router),
            abi=ROUTER_ABI,
        )

        amount_in_wei = self.w3.to_wei(amount_bnb, "ether")
        amount_out_min = 0

        try:
            amounts = await router.functions.getAmountsOut(
                amount_in_wei,
                [
                    self.w3.to_checksum_address(WBNB_ADDRESS),
                    self.w3.to_checksum_address(token_address),
                ],
            ).call()
            expected_out = amounts[1]
            amount_out_min = int(expected_out * (100 - slippage) / 100)
        except Exception as e:
            logger.warning("getAmountsOut failed, using 0 min: %s", e)

        nonce = await self.conn.get_nonce(self.config.wallet_address)
        gas_price = await self.conn.get_gas_price()
        deadline = int(time.time()) + 300

        tx = await router.functions.swapExactETHForTokensSupportingFeeOnTransferTokens(
            amount_out_min,
            [
                self.w3.to_checksum_address(WBNB_ADDRESS),
                self.w3.to_checksum_address(token_address),
            ],
            self.w3.to_checksum_address(self.config.wallet_address),
            deadline,
        ).build_transaction({
            "from": self.w3.to_checksum_address(self.config.wallet_address),
            "value": amount_in_wei,
            "gas": self.config.gas_limit,
            "gasPrice": gas_price,
            "nonce": nonce,
            "chainId": 56,
        })

        logger.info(
            "BUY TX: %s | Amount: %.4f BNB | MinOut: %d | Gas: %d gwei",
            token_address,
            amount_bnb,
            amount_out_min,
            gas_price // 10**9,
        )

        tx_hash = await self.conn.send_transaction(tx)
        receipt = await self.conn.wait_for_receipt(tx_hash)

        success = receipt["status"] == 1
        if success:
            token_balance = await self._get_token_balance(token_address)
            self._active_positions[token_address] = {
                "buy_tx": tx_hash,
                "buy_price_bnb": amount_bnb,
                "token_balance": token_balance,
                "buy_time": time.time(),
                "buy_block": receipt["blockNumber"],
            }
            logger.info(
                "BUY SUCCESS: %s | TX: %s | Tokens: %d",
                token_address,
                tx_hash,
                token_balance,
            )
        else:
            logger.error("BUY FAILED: %s | TX: %s", token_address, tx_hash)

        return {
            "success": success,
            "tx_hash": tx_hash,
            "gas_used": receipt["gasUsed"],
        }

    async def sell_token(
        self,
        token_address: str,
        amount_tokens: int = 0,
        slippage: float = 0,
    ) -> dict:
        if slippage <= 0:
            slippage = self.config.slippage_percent

        if amount_tokens <= 0:
            amount_tokens = await self._get_token_balance(token_address)

        if amount_tokens <= 0:
            logger.warning("No tokens to sell for %s", token_address)
            return {"success": False, "tx_hash": "", "gas_used": 0}

        await self._approve_token(token_address, amount_tokens)

        router = self.w3.eth.contract(
            address=self.w3.to_checksum_address(self.config.pancake_router),
            abi=ROUTER_ABI,
        )

        amount_out_min = 0
        try:
            amounts = await router.functions.getAmountsOut(
                amount_tokens,
                [
                    self.w3.to_checksum_address(token_address),
                    self.w3.to_checksum_address(WBNB_ADDRESS),
                ],
            ).call()
            expected_bnb = amounts[1]
            amount_out_min = int(expected_bnb * (100 - slippage) / 100)
        except Exception as e:
            logger.warning("getAmountsOut failed for sell: %s", e)

        nonce = await self.conn.get_nonce(self.config.wallet_address)
        gas_price = await self.conn.get_gas_price()
        deadline = int(time.time()) + 300

        tx = await router.functions.swapExactTokensForETHSupportingFeeOnTransferTokens(
            amount_tokens,
            amount_out_min,
            [
                self.w3.to_checksum_address(token_address),
                self.w3.to_checksum_address(WBNB_ADDRESS),
            ],
            self.w3.to_checksum_address(self.config.wallet_address),
            deadline,
        ).build_transaction({
            "from": self.w3.to_checksum_address(self.config.wallet_address),
            "gas": self.config.gas_limit,
            "gasPrice": gas_price,
            "nonce": nonce,
            "chainId": 56,
        })

        logger.info(
            "SELL TX: %s | Tokens: %d | MinOut: %d wei",
            token_address,
            amount_tokens,
            amount_out_min,
        )

        tx_hash = await self.conn.send_transaction(tx)
        receipt = await self.conn.wait_for_receipt(tx_hash)

        success = receipt["status"] == 1
        if success:
            self._active_positions.pop(token_address, None)
            logger.info("SELL SUCCESS: %s | TX: %s", token_address, tx_hash)
        else:
            logger.error("SELL FAILED: %s | TX: %s", token_address, tx_hash)

        return {
            "success": success,
            "tx_hash": tx_hash,
            "gas_used": receipt["gasUsed"],
        }

    async def _approve_token(self, token_address: str, amount: int):
        token_contract = self.w3.eth.contract(
            address=self.w3.to_checksum_address(token_address),
            abi=ERC20_ABI,
        )

        current_allowance = await token_contract.functions.allowance(
            self.w3.to_checksum_address(self.config.wallet_address),
            self.w3.to_checksum_address(self.config.pancake_router),
        ).call()

        if current_allowance >= amount:
            return

        nonce = await self.conn.get_nonce(self.config.wallet_address)
        gas_price = await self.conn.get_gas_price()

        tx = await token_contract.functions.approve(
            self.w3.to_checksum_address(self.config.pancake_router),
            MAX_UINT256,
        ).build_transaction({
            "from": self.w3.to_checksum_address(self.config.wallet_address),
            "gas": 100000,
            "gasPrice": gas_price,
            "nonce": nonce,
            "chainId": 56,
        })

        tx_hash = await self.conn.send_transaction(tx)
        await self.conn.wait_for_receipt(tx_hash)
        logger.info("Approve TX: %s for %s", tx_hash, token_address)

    async def _get_token_balance(self, token_address: str) -> int:
        token_contract = self.w3.eth.contract(
            address=self.w3.to_checksum_address(token_address),
            abi=ERC20_ABI,
        )
        return await token_contract.functions.balanceOf(
            self.w3.to_checksum_address(self.config.wallet_address)
        ).call()

    async def check_profit(self, token_address: str) -> dict:
        position = self._active_positions.get(token_address)
        if not position:
            return {"profit_pct": 0, "should_sell": False, "reason": "no_position"}

        try:
            router = self.w3.eth.contract(
                address=self.w3.to_checksum_address(self.config.pancake_router),
                abi=ROUTER_ABI,
            )

            current_balance = await self._get_token_balance(token_address)
            if current_balance <= 0:
                return {"profit_pct": 0, "should_sell": False, "reason": "no_balance"}

            amounts = await router.functions.getAmountsOut(
                current_balance,
                [
                    self.w3.to_checksum_address(token_address),
                    self.w3.to_checksum_address(WBNB_ADDRESS),
                ],
            ).call()
            current_value_bnb = float(self.w3.from_wei(amounts[1], "ether"))

            buy_price = position["buy_price_bnb"]
            profit_pct = ((current_value_bnb - buy_price) / buy_price) * 100

            should_sell = False
            reason = "hold"

            if profit_pct >= self.config.take_profit_percent:
                should_sell = True
                reason = "take_profit"
            elif profit_pct <= -self.config.stop_loss_percent:
                should_sell = True
                reason = "stop_loss"

            return {
                "profit_pct": profit_pct,
                "current_value_bnb": current_value_bnb,
                "should_sell": should_sell,
                "reason": reason,
            }

        except Exception as e:
            logger.error("Profit check error: %s", e)
            return {"profit_pct": 0, "should_sell": False, "reason": "error"}
