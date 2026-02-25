import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Solana RPC
    SOLANA_WS_URL: str = os.getenv("SOLANA_WS_URL", "wss://api.mainnet-beta.solana.com")
    SOLANA_HTTP_URL: str = os.getenv("SOLANA_HTTP_URL", "https://api.mainnet-beta.solana.com")

    # Pump.fun program
    PUMP_FUN_PROGRAM: str = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
    GRADUATION_SOL_THRESHOLD: float = 85.0  # SOL needed for graduation
    LAMPORTS_PER_SOL: int = 1_000_000_000

    # Budget
    BUDGET_USD: float = float(os.getenv("BUDGET_USD", "50"))
    SOL_PRICE_USD: float = float(os.getenv("SOL_PRICE_USD", "140"))

    # Trade params
    BUY_AMOUNT_SOL: float = float(os.getenv("BUY_AMOUNT_SOL", "0.02"))
    TAKE_PROFIT_PCT: float = float(os.getenv("TAKE_PROFIT_PCT", "100"))
    STOP_LOSS_PCT: float = float(os.getenv("STOP_LOSS_PCT", "30"))
    TIMEOUT_SECONDS: int = int(os.getenv("TIMEOUT_SECONDS", "300"))
    MAX_POSITIONS: int = int(os.getenv("MAX_POSITIONS_PER_STRATEGY", "5"))

    # KOTH strategy
    KOTH_MIN_CURVE_PCT: float = float(os.getenv("KOTH_MIN_CURVE_PCT", "40"))
    KOTH_MAX_CURVE_PCT: float = float(os.getenv("KOTH_MAX_CURVE_PCT", "65"))
    KOTH_MIN_UNIQUE_BUYERS: int = int(os.getenv("KOTH_MIN_UNIQUE_BUYERS", "12"))
    KOTH_MIN_VELOCITY: float = float(os.getenv("KOTH_MIN_VELOCITY", "0.3"))

    # Velocity strategy
    VELOCITY_SPIKE_MULTIPLIER: float = float(os.getenv("VELOCITY_SPIKE_MULTIPLIER", "3.0"))
    VELOCITY_MIN_CURVE_PCT: float = float(os.getenv("VELOCITY_MIN_CURVE_PCT", "10"))
    VELOCITY_MIN_UNIQUE_BUYERS: int = int(os.getenv("VELOCITY_MIN_UNIQUE_BUYERS", "8"))
    VELOCITY_WINDOW_SECONDS: int = int(os.getenv("VELOCITY_WINDOW_SECONDS", "60"))

    # Migration strategy
    MIGRATION_HOLD_SECONDS: int = int(os.getenv("MIGRATION_HOLD_SECONDS", "300"))

    @property
    def budget_sol(self) -> float:
        return self.BUDGET_USD / self.SOL_PRICE_USD
