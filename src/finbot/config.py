"""Configuração operacional do FinBot."""

from dataclasses import dataclass, field
from enum import Enum
import os

VALID_TRADING_MODES = {"paper", "live"}
DEFAULT_TRADING_MODE = "paper"


class BinanceEnvironment(str, Enum):
    """Ambiente da API da Binance com separação estrita de execução."""

    PRODUCTION = "production"
    SPOT_TESTNET = "spot_testnet"


@dataclass(frozen=True)
class Config:
    """Configurações operacionais básicas e imutáveis da aplicação."""

    app_name: str = "FinBot"
    environment: str = "local"
    trading_mode: str = "paper"
    log_level: str = "INFO"
    exchange_id: str = "binance"
    binance_environment: BinanceEnvironment = BinanceEnvironment.PRODUCTION
    testnet_execution_enabled: bool = False
    symbol: str = "BTC/USDT"
    timeframe: str = "1m"
    candle_limit: int = 20
    short_window: int = 5
    long_window: int = 10
    backtest_initial_cash: float = 10000.0
    backtest_commission: float = 0.001
    backtest_timeframe: str = "5m"
    backtest_candle_limit: int = 500
    backtest_data_dir: str = "data/backtest"
    paper_initial_cash: float = 10000.0
    paper_trade_notional: float = 100.0
    paper_commission: float = 0.001
    paper_db_path: str = "data/finbot_paper.sqlite3"
    paper_timeframe: str = "1m"
    paper_candle_limit: int = 20
    risk_max_position_notional: float = 100.0
    risk_max_daily_loss: float = 50.0
    risk_cooldown_candles: int = 1
    risk_stop_loss_pct: float = 0.02
    risk_kill_switch: bool = False
    adaptive_mode: str = "off"
    adaptive_model_id: str = ""
    adaptive_registry_db: str = "data/lab/results/model_registry/model_registry.sqlite3"
    live_trading_acknowledged: bool = False
    live_max_order_notional: float = 100.0
    live_execution_enabled: bool = False
    live_micro_order_max_notional: float = 15.0
    real_order_submission_enabled: bool = False
    binance_api_key: str = field(default="", repr=False)
    binance_api_secret: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        """Sanitiza trading_mode e binance_environment garantindo valores suportados."""
        mode = (self.trading_mode or "").strip().lower()
        if mode not in VALID_TRADING_MODES:
            object.__setattr__(self, "trading_mode", DEFAULT_TRADING_MODE)
        else:
            object.__setattr__(self, "trading_mode", mode)

        if isinstance(self.binance_environment, str):
            clean_env = self.binance_environment.strip().lower()
            if clean_env in ("spot_testnet", "testnet"):
                object.__setattr__(self, "binance_environment", BinanceEnvironment.SPOT_TESTNET)
            else:
                object.__setattr__(self, "binance_environment", BinanceEnvironment.PRODUCTION)
        elif not isinstance(self.binance_environment, BinanceEnvironment):
            object.__setattr__(self, "binance_environment", BinanceEnvironment.PRODUCTION)


def get_config() -> Config:
    """Retorna a configuração operacional a partir de variáveis de ambiente com defaults seguros.

    NOTA DE SEGURANÇA (FASE 8.2A):
    Credenciais de produção da Binance NÃO são lidas de variáveis de ambiente ou arquivos .env.
    O armazenamento oficial de credenciais de produção no PC Forte é o Windows Credential Manager,
    gerenciado via provedor `finbot.credentials.WindowsCredentialProvider`.
    """
    raw_mode = os.getenv("TRADING_MODE", DEFAULT_TRADING_MODE).strip().lower()
    trading_mode = raw_mode if raw_mode in VALID_TRADING_MODES else DEFAULT_TRADING_MODE

    raw_ack = os.getenv("LIVE_TRADING_ACKNOWLEDGED", "false").strip().lower()
    live_trading_acknowledged = raw_ack in ("1", "true", "yes")

    raw_live_max = os.getenv("LIVE_MAX_ORDER_NOTIONAL", "100.0").strip()
    try:
        live_max_order_notional = float(raw_live_max)
    except ValueError:
        live_max_order_notional = 100.0

    raw_exec = os.getenv("LIVE_EXECUTION_ENABLED", "false").strip().lower()
    live_execution_enabled = raw_exec in ("1", "true", "yes")

    raw_micro = os.getenv("LIVE_MICRO_ORDER_MAX_NOTIONAL", "15.0").strip()
    try:
        live_micro_order_max_notional = float(raw_micro)
    except ValueError:
        live_micro_order_max_notional = 15.0

    raw_real = os.getenv("REAL_ORDER_SUBMISSION_ENABLED", "false").strip().lower()
    real_order_submission_enabled = raw_real in ("1", "true", "yes")

    raw_env = os.getenv("BINANCE_ENVIRONMENT", "production").strip().lower()
    if raw_env in ("spot_testnet", "testnet"):
        binance_env = BinanceEnvironment.SPOT_TESTNET
    else:
        binance_env = BinanceEnvironment.PRODUCTION

    raw_testnet_exec = os.getenv("TESTNET_EXECUTION_ENABLED", "false").strip().lower()
    testnet_execution_enabled = raw_testnet_exec in ("1", "true", "yes")

    return Config(
        trading_mode=trading_mode,
        binance_environment=binance_env,
        testnet_execution_enabled=testnet_execution_enabled,
        live_trading_acknowledged=live_trading_acknowledged,
        live_max_order_notional=live_max_order_notional,
        live_execution_enabled=live_execution_enabled,
        live_micro_order_max_notional=live_micro_order_max_notional,
        real_order_submission_enabled=real_order_submission_enabled,
    )

