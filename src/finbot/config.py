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


def get_config() -> Config:
    """Retorna a configuração padrão para execução local."""
    return Config()
