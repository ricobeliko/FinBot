"""Configuração local do FinBot para a FASE 3 (Strategy Engine)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    """Configurações operacionais básicas e imutáveis da aplicação."""

    app_name: str = "FinBot"
    environment: str = "local"
    trading_mode: str = "disabled"
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


def get_config() -> Config:
    """Retorna a configuração padrão para execução local."""
    return Config()
