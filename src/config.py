import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


BSC_PUBLIC_NODES = [
    "https://bsc.publicnode.com",
    "https://bsc-dataseed1.binance.org",
    "https://bsc-dataseed2.binance.org",
    "https://bsc-dataseed3.binance.org",
    "https://bsc-dataseed4.binance.org",
    "https://bsc-dataseed1.defibit.io",
    "https://bsc-dataseed2.defibit.io",
    "https://bsc-dataseed1.ninicoin.io",
    "https://bsc-dataseed2.ninicoin.io",
]

PANCAKE_FACTORY_V2 = "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73"
PANCAKE_ROUTER_V2 = "0x10ED43C718714eb63d5aA57B78B54704E256024E"
WBNB_ADDRESS = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"
BUSD_ADDRESS = "0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56"
USDT_ADDRESS = "0x55d398326f99059fF775485246999027B3197955"

FACTORY_ABI = [
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "token0", "type": "address"},
            {"indexed": True, "name": "token1", "type": "address"},
            {"indexed": False, "name": "pair", "type": "address"},
            {"indexed": False, "name": "", "type": "uint256"},
        ],
        "name": "PairCreated",
        "type": "event",
    },
    {
        "constant": True,
        "inputs": [
            {"name": "tokenA", "type": "address"},
            {"name": "tokenB", "type": "address"},
        ],
        "name": "getPair",
        "outputs": [{"name": "pair", "type": "address"}],
        "type": "function",
    },
]

ROUTER_ABI = [
    {
        "inputs": [
            {"name": "amountOutMin", "type": "uint256"},
            {"name": "path", "type": "address[]"},
            {"name": "to", "type": "address"},
            {"name": "deadline", "type": "uint256"},
        ],
        "name": "swapExactETHForTokensSupportingFeeOnTransferTokens",
        "outputs": [],
        "stateMutability": "payable",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "amountIn", "type": "uint256"},
            {"name": "amountOutMin", "type": "uint256"},
            {"name": "path", "type": "address[]"},
            {"name": "to", "type": "address"},
            {"name": "deadline", "type": "uint256"},
        ],
        "name": "swapExactTokensForETHSupportingFeeOnTransferTokens",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "amountIn", "type": "uint256"},
            {"name": "path", "type": "address[]"},
        ],
        "name": "getAmountsOut",
        "outputs": [{"name": "amounts", "type": "uint256[]"}],
        "stateMutability": "view",
        "type": "function",
    },
]

PAIR_ABI = [
    {
        "constant": True,
        "inputs": [],
        "name": "getReserves",
        "outputs": [
            {"name": "_reserve0", "type": "uint112"},
            {"name": "_reserve1", "type": "uint112"},
            {"name": "_blockTimestampLast", "type": "uint32"},
        ],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "token0",
        "outputs": [{"name": "", "type": "address"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "token1",
        "outputs": [{"name": "", "type": "address"}],
        "type": "function",
    },
]

ERC20_ABI = [
    {
        "constant": True,
        "inputs": [],
        "name": "name",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "totalSupply",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_spender", "type": "address"},
            {"name": "_value", "type": "uint256"},
        ],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [
            {"name": "_owner", "type": "address"},
            {"name": "_spender", "type": "address"},
        ],
        "name": "allowance",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "owner",
        "outputs": [{"name": "", "type": "address"}],
        "type": "function",
    },
]


@dataclass
class BotConfig:
    bsc_wss_url: str = os.getenv("BSC_WSS_URL", "wss://bsc-ws-node.nariox.org:443")
    bsc_https_url: str = os.getenv("BSC_HTTPS_URL", "https://bsc.publicnode.com")
    private_key: str = os.getenv("PRIVATE_KEY", "")
    wallet_address: str = os.getenv("WALLET_ADDRESS", "")

    buy_amount_bnb: float = float(os.getenv("BUY_AMOUNT_BNB", "0.1"))
    min_liquidity_usd: float = float(os.getenv("MIN_LIQUIDITY_USD", "1500"))
    max_buy_tax: float = float(os.getenv("MAX_BUY_TAX", "10"))
    max_sell_tax: float = float(os.getenv("MAX_SELL_TAX", "10"))
    slippage_percent: float = float(os.getenv("SLIPPAGE_PERCENT", "12"))
    gas_price_gwei: int = int(os.getenv("GAS_PRICE_GWEI", "5"))
    gas_limit: int = int(os.getenv("GAS_LIMIT", "500000"))

    take_profit_percent: float = float(os.getenv("TAKE_PROFIT_PERCENT", "100"))
    stop_loss_percent: float = float(os.getenv("STOP_LOSS_PERCENT", "30"))

    ml_min_score: float = float(os.getenv("ML_MIN_SCORE", "0.7"))
    poll_interval_ms: int = int(os.getenv("POLL_INTERVAL_MS", "100"))
    auto_retrain_every: int = int(os.getenv("AUTO_RETRAIN_EVERY", "50"))
    trade_history_path: str = os.getenv("TRADE_HISTORY_PATH", "data/trades.csv")
    paper_trading: bool = os.getenv("PAPER_TRADING", "false").lower() in ("true", "1", "yes")

    pancake_factory: str = PANCAKE_FACTORY_V2
    pancake_router: str = PANCAKE_ROUTER_V2
    wbnb_address: str = WBNB_ADDRESS

    quote_tokens: list = field(default_factory=lambda: [
        WBNB_ADDRESS,
        BUSD_ADDRESS,
        USDT_ADDRESS,
    ])
