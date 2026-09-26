"""Configuração mínima local do FinBot para a FASE 1 (Python Core)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    """Configurações operacionais básicas e imutáveis da aplicação."""

    app_name: str = "FinBot"
    environment: str = "local"
    trading_mode: str = "disabled"
    log_level: str = "INFO"


def get_config() -> Config:
    """Retorna a configuração padrão para execução local."""
    return Config()
