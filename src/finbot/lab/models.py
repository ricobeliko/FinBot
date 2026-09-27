"""Modelos de dados e estruturas para o FinBot Lab.

Define estruturas de divisão cronológica, parâmetros de grid, métricas por partição
e metadados de auditoria do sweep experimental.
"""

from dataclasses import asdict, dataclass
from typing import Any
import pandas as pd


@dataclass(frozen=True)
class SplitRatio:
    """Proporção de particionamento cronológico sem shuffle."""

    train: float = 0.60
    validation: float = 0.20
    test: float = 0.20

    def __post_init__(self) -> None:
        total = round(self.train + self.validation + self.test, 6)
        if total != 1.0:
            raise ValueError(
                f"As proporções de split devem somar 1.0 (recebido: {total})."
            )
        if self.train <= 0 or self.validation <= 0 or self.test <= 0:
            raise ValueError("Todas as proporções de split devem ser estritamente positivas.")


@dataclass(frozen=True)
class ChronologicalSplit:
    """Divisão cronológica estrita de um dataset histórico."""

    train_df: pd.DataFrame
    validation_df: pd.DataFrame
    test_df: pd.DataFrame
    train_count: int
    val_count: int
    test_count: int
    total_count: int
    start_time: str
    end_time: str


@dataclass(frozen=True)
class SMAParams:
    """Parâmetros de médias móveis para o candidato."""

    short_window: int
    long_window: int

    def __post_init__(self) -> None:
        if self.short_window < 1:
            raise ValueError(f"short_window deve ser >= 1 (recebido: {self.short_window})")
        if self.long_window <= self.short_window:
            raise ValueError(
                f"short_window ({self.short_window}) deve ser estritamente menor que long_window ({self.long_window})"
            )


@dataclass(frozen=True)
class PartitionMetrics:
    """Métricas de performance obtidas em uma partição específica (Train, Val ou Test)."""

    final_equity: float
    return_pct: float
    trades: int
    wins: int
    losses: int
    win_rate: float | None
    max_drawdown: float
    profit_factor: float | None
    buy_and_hold: float


@dataclass(frozen=True)
class CandidateResult:
    """Resultado consolidado da avaliação de um candidato nas 3 partições."""

    params: SMAParams
    train: PartitionMetrics
    validation: PartitionMetrics
    test: PartitionMetrics

    def to_dict(self) -> dict[str, Any]:
        """Converte o resultado em dicionário tabular plano para exportação CSV."""
        return {
            "short_window": self.params.short_window,
            "long_window": self.params.long_window,
            # Train
            "train_return_pct": self.train.return_pct,
            "train_final_equity": self.train.final_equity,
            "train_trades": self.train.trades,
            "train_wins": self.train.wins,
            "train_losses": self.train.losses,
            "train_win_rate": self.train.win_rate,
            "train_max_drawdown": self.train.max_drawdown,
            "train_profit_factor": self.train.profit_factor,
            "train_buy_and_hold": self.train.buy_and_hold,
            # Validation
            "val_return_pct": self.validation.return_pct,
            "val_final_equity": self.validation.final_equity,
            "val_trades": self.validation.trades,
            "val_wins": self.validation.wins,
            "val_losses": self.validation.losses,
            "val_win_rate": self.validation.win_rate,
            "val_max_drawdown": self.validation.max_drawdown,
            "val_profit_factor": self.validation.profit_factor,
            "val_buy_and_hold": self.validation.buy_and_hold,
            # Test (out-of-sample)
            "test_return_pct": self.test.return_pct,
            "test_final_equity": self.test.final_equity,
            "test_trades": self.test.trades,
            "test_wins": self.test.wins,
            "test_losses": self.test.losses,
            "test_win_rate": self.test.win_rate,
            "test_max_drawdown": self.test.max_drawdown,
            "test_profit_factor": self.test.profit_factor,
            "test_buy_and_hold": self.test.buy_and_hold,
        }


@dataclass(frozen=True)
class SweepMetadata:
    """Metadados de auditoria e reprodutibilidade do sweep de parâmetros."""

    dataset_path: str
    dataset_hash: str
    symbol: str
    timeframe: str
    total_candles: int
    train_candles: int
    val_candles: int
    test_candles: int
    preset: str
    workers: int
    total_combinations: int
    initial_cash: float
    commission: float
    started_at: str
    completed_at: str
    elapsed_seconds: float

    def to_dict(self) -> dict[str, Any]:
        """Converte os metadados em dicionário para exportação JSON."""
        return asdict(self)
