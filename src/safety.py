import logging
from dataclasses import dataclass
from web3 import AsyncWeb3

from src.config import BotConfig, ERC20_ABI, ROUTER_ABI, WBNB_ADDRESS

logger = logging.getLogger("sniper.safety")

DEAD_ADDRESSES = {
    "0x0000000000000000000000000000000000000000",
    "0x000000000000000000000000000000000000dEaD",
    "0x0000000000000000000000000000000000000001",
}


@dataclass
class SafetyReport:
    is_honeypot: bool = True
    buy_tax: float = 100.0
    sell_tax: float = 100.0
    is_ownership_renounced: bool = False
    has_proxy: bool = False
    holder_count_estimate: int = 0
    top_holder_percent: float = 100.0
    is_mintable: bool = False
    liquidity_locked: bool = False
    score: float = 0.0

    @property
    def is_safe(self) -> bool:
        return not self.is_honeypot and self.score >= 0.5

    def to_features(self) -> list[float]:
        return [
            0.0 if self.is_honeypot else 1.0,
            self.buy_tax,
            self.sell_tax,
            1.0 if self.is_ownership_renounced else 0.0,
            0.0 if self.has_proxy else 1.0,
            float(self.holder_count_estimate),
            self.top_holder_percent,
            0.0 if self.is_mintable else 1.0,
            1.0 if self.liquidity_locked else 0.0,
        ]


class SafetyAnalyzer:
    def __init__(self, w3: AsyncWeb3, config: BotConfig):
        self.w3 = w3
        self.config = config

    async def analyze(
        self,
        token_address: str,
        pair_address: str,
        quote_token: str,
    ) -> SafetyReport:
        report = SafetyReport()

        try:
            token_contract = self.w3.eth.contract(
                address=self.w3.to_checksum_address(token_address),
                abi=ERC20_ABI,
            )

            ownership_renounced = await self._check_ownership(token_contract)
            report.is_ownership_renounced = ownership_renounced

            honeypot, buy_tax, sell_tax = await self._simulate_trade(
                token_address, quote_token
            )
            report.is_honeypot = honeypot
            report.buy_tax = buy_tax
            report.sell_tax = sell_tax

            top_holder_pct = await self._check_top_holders(
                token_contract, token_address, pair_address
            )
            report.top_holder_percent = top_holder_pct

            is_mintable = await self._check_mintable(token_address)
            report.is_mintable = is_mintable

            report.score = self._calculate_score(report)

            logger.info(
                "Safety: %s | HP=%s BuyTax=%.1f%% SellTax=%.1f%% "
                "Renounced=%s Score=%.2f",
                token_address[:10],
                report.is_honeypot,
                report.buy_tax,
                report.sell_tax,
                report.is_ownership_renounced,
                report.score,
            )

        except Exception as e:
            logger.error("Safety analysis error for %s: %s", token_address, e)

        return report

    async def _check_ownership(self, token_contract) -> bool:
        try:
            owner = await token_contract.functions.owner().call()
            return owner.lower() in [addr.lower() for addr in DEAD_ADDRESSES]
        except Exception:
            return False

    async def _simulate_trade(
        self, token_address: str, quote_token: str
    ) -> tuple[bool, float, float]:
        try:
            router = self.w3.eth.contract(
                address=self.w3.to_checksum_address(self.config.pancake_router),
                abi=ROUTER_ABI,
            )

            test_amount = self.w3.to_wei(0.001, "ether")

            buy_path = [
                self.w3.to_checksum_address(WBNB_ADDRESS),
                self.w3.to_checksum_address(token_address),
            ]
            sell_path = [
                self.w3.to_checksum_address(token_address),
                self.w3.to_checksum_address(WBNB_ADDRESS),
            ]

            buy_amounts = await router.functions.getAmountsOut(
                test_amount, buy_path
            ).call()
            expected_tokens = buy_amounts[1]

            if expected_tokens == 0:
                return True, 100.0, 100.0

            sell_amounts = await router.functions.getAmountsOut(
                expected_tokens, sell_path
            ).call()
            returned_bnb = sell_amounts[1]

            total_tax = (1 - returned_bnb / test_amount) * 100
            buy_tax = total_tax / 2
            sell_tax = total_tax / 2

            is_honeypot = returned_bnb == 0 or total_tax > 80

            return is_honeypot, max(0, buy_tax), max(0, sell_tax)

        except Exception as e:
            logger.warning("Trade simulation failed: %s", e)
            return True, 100.0, 100.0

    async def _check_top_holders(
        self,
        token_contract,
        token_address: str,
        pair_address: str,
    ) -> float:
        try:
            total_supply = await token_contract.functions.totalSupply().call()
            if total_supply == 0:
                return 100.0

            pair_balance = await token_contract.functions.balanceOf(
                self.w3.to_checksum_address(pair_address)
            ).call()

            dead_balance = 0
            for dead_addr in DEAD_ADDRESSES:
                try:
                    bal = await token_contract.functions.balanceOf(
                        self.w3.to_checksum_address(dead_addr)
                    ).call()
                    dead_balance += bal
                except Exception:
                    pass

            circulating = total_supply - pair_balance - dead_balance
            if circulating <= 0:
                return 0.0

            return (circulating / total_supply) * 100

        except Exception as e:
            logger.warning("Top holder check failed: %s", e)
            return 100.0

    async def _check_mintable(self, token_address: str) -> bool:
        try:
            code = await self.w3.eth.get_code(
                self.w3.to_checksum_address(token_address)
            )
            code_hex = code.hex().lower()
            mint_signatures = ["40c10f19", "a0712d68", "4e6ec247"]
            return any(sig in code_hex for sig in mint_signatures)
        except Exception:
            return False

    @staticmethod
    def _calculate_score(report: SafetyReport) -> float:
        score = 1.0

        if report.is_honeypot:
            return 0.0

        if report.buy_tax > 50:
            score -= 0.5
        elif report.buy_tax > 20:
            score -= 0.3
        elif report.buy_tax > 10:
            score -= 0.15

        if report.sell_tax > 50:
            score -= 0.5
        elif report.sell_tax > 20:
            score -= 0.3
        elif report.sell_tax > 10:
            score -= 0.15

        if report.is_ownership_renounced:
            score += 0.1

        if report.is_mintable:
            score -= 0.2

        if report.top_holder_percent > 50:
            score -= 0.3
        elif report.top_holder_percent > 30:
            score -= 0.15

        return max(0.0, min(1.0, score))
