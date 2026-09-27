"""Configuração operacional do FinBot."""

from dataclasses import dataclass, field
import os

VALID_TRADING_MODES = {"paper", "live"}
DEFAULT_TRADING_MODE = "paper"


@dataclass(frozen=True)
class Config:
    """Configurações operacionais básicas e imutáveis da aplicação."""

    app_name: str = "FinBot"
    environment: str = "local"
    trading_mode: str = "paper"
    log_level: str = "INFO"
    exchange_id: str = "binance"
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
    binance_api_key: str = field(default="", repr=False)
    binance_api_secret: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        """Sanitiza trading_mode garantindo que apenas valores suportados sejam aceitos."""
        mode = (self.trading_mode or "").strip().lower()
        if mode not in VALID_TRADING_MODES:
            object.__setattr__(self, "trading_mode", DEFAULT_TRADING_MODE)
        else:
            object.__setattr__(self, "trading_mode", mode)


def get_config() -> Config:
    """Retorna a configuração operacional a partir de variáveis de ambiente com defaults seguros.

    NOTA DE SEGURANÇA (FASE 8.2A):
    Credenciais de produção da Binance NÃO são lidas de variáveis de ambiente ou arquivos .env.
    O armazenamento oficial de credenciais de produção no PC Forte é o Windows Credential Manager,
    gerenciado via provedor `finbot.credentials.WindowsCredentialProvider`.
    """
    raw_mode = os.getenv("TRADING_MODE", DEFAULT_TRADING_MODE).strip().lower()
    trading_mode = raw_mode if raw_mode in VALID_TRADING_MODES else DEFAULT_TRADING_MODE

    return Config(
        trading_mode=trading_mode,
    )
