import logging
from typing import Optional

from web3 import AsyncWeb3

from src.config import BotConfig, PAIR_ABI, WBNB_ADDRESS

logger = logging.getLogger("sniper.liquidity")


class LiquidityInfo:
    def __init__(
        self,
        pair_address: str,
        token_reserve: int,
        quote_reserve: int,
        quote_reserve_bnb: float,
        token_decimals: int,
    ):
        self.pair_address = pair_address
        self.token_reserve = token_reserve
        self.quote_reserve = quote_reserve
        self.quote_reserve_bnb = quote_reserve_bnb
        self.token_decimals = token_decimals

    @property
    def token_price_bnb(self) -> float:
        if self.token_reserve == 0:
            return 0.0
        return self.quote_reserve_bnb / (
            self.token_reserve / (10 ** self.token_decimals)
        )


class LiquidityChecker:
    def __init__(self, w3: AsyncWeb3, config: BotConfig):
        self.w3 = w3
        self.config = config

    async def check_liquidity(
        self,
        pair_address: str,
        token_address: str,
        quote_token: str,
        token_decimals: int = 18,
    ) -> Optional[LiquidityInfo]:
        try:
            pair_contract = self.w3.eth.contract(
                address=self.w3.to_checksum_address(pair_address),
                abi=PAIR_ABI,
            )

            reserves = await pair_contract.functions.getReserves().call()
            token0 = await pair_contract.functions.token0().call()

            reserve0, reserve1 = reserves[0], reserves[1]

            if token0.lower() == token_address.lower():
                token_reserve = reserve0
                quote_reserve = reserve1
            else:
                token_reserve = reserve1
                quote_reserve = reserve0

            quote_reserve_bnb = await self._convert_to_bnb(
                quote_reserve, quote_token
            )

            return LiquidityInfo(
                pair_address=pair_address,
                token_reserve=token_reserve,
                quote_reserve=quote_reserve,
                quote_reserve_bnb=quote_reserve_bnb,
                token_decimals=token_decimals,
            )

        except Exception as e:
            logger.error("Liquidity check error for %s: %s", pair_address, e)
            return None

    async def _convert_to_bnb(self, amount: int, quote_token: str) -> float:
        if quote_token.lower() == WBNB_ADDRESS.lower():
            return float(self.w3.from_wei(amount, "ether"))

        try:
            from src.config import ROUTER_ABI

            router = self.w3.eth.contract(
                address=self.w3.to_checksum_address(self.config.pancake_router),
                abi=ROUTER_ABI,
            )
            amounts = await router.functions.getAmountsOut(
                amount,
                [
                    self.w3.to_checksum_address(quote_token),
                    self.w3.to_checksum_address(WBNB_ADDRESS),
                ],
            ).call()
            return float(self.w3.from_wei(amounts[1], "ether"))
        except Exception as e:
            logger.warning("BNB conversion failed: %s", e)
            return float(self.w3.from_wei(amount, "ether"))

    async def meets_minimum(
        self,
        pair_address: str,
        token_address: str,
        quote_token: str,
        token_decimals: int = 18,
    ) -> tuple[bool, Optional[LiquidityInfo]]:
        liq = await self.check_liquidity(
            pair_address, token_address, quote_token, token_decimals
        )
        if liq is None:
            return False, None

        meets = liq.quote_reserve_bnb >= self.config.min_liquidity_bnb
        logger.info(
            "Liquidity: %.2f BNB (min: %.2f) -> %s",
            liq.quote_reserve_bnb,
            self.config.min_liquidity_bnb,
            "PASS" if meets else "SKIP",
        )
        return meets, liq
