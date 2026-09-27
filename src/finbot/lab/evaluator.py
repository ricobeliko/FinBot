"""Módulo de avaliação de candidatos do FinBot Lab.

Executa simulações históricas reproduzíveis sobre as partições (Train, Validation, Test)
reutilizando o motor puro oficial de `finbot.backtest.run_backtest`.
"""

import pandas as pd

from finbot.backtest import BacktestResult, run_backtest
from finbot.lab.models import CandidateResult, PartitionMetrics, SMAParams


def evaluate_partition(
    df: pd.DataFrame,
    params: SMAParams,
    initial_cash: float = 10000.0,
    commission: float = 0.001,
) -> PartitionMetrics:
    """Executa o backtest da estratégia sobre um recorte específico de candles.

    Reutiliza diretamente o motor oficial `run_backtest` sem duplicar nenhuma lógica.
    """
    res: BacktestResult = run_backtest(
        df=df,
        initial_cash=initial_cash,
        commission=commission,
        short_window=params.short_window,
        long_window=params.long_window,
    )

    return PartitionMetrics(
        final_equity=res.final_equity,
        return_pct=res.total_return_pct,
        trades=res.trades_count,
        wins=res.wins,
        losses=res.losses,
        win_rate=res.win_rate_pct,
        max_drawdown=res.max_drawdown_pct,
        profit_factor=res.profit_factor,
        buy_and_hold=res.buy_and_hold_pct,
    )


def evaluate_candidate(
    train_df: pd.DataFrame,
    validation_df: pd.DataFrame,
    test_df: pd.DataFrame,
    params: SMAParams,
    initial_cash: float = 10000.0,
    commission: float = 0.001,
) -> CandidateResult:
    """Avalia o candidato de parâmetros sequencialmente nas partições Train, Validation e Test.

    O processo de otimização/screening deve considerar unicamente o Train.
    Validation e Test atuam como verificadores out-of-sample sem retroalimentação.
    """
    train_metrics = evaluate_partition(
        df=train_df,
        params=params,
        initial_cash=initial_cash,
        commission=commission,
    )

    val_metrics = evaluate_partition(
        df=validation_df,
        params=params,
        initial_cash=initial_cash,
        commission=commission,
    )

    test_metrics = evaluate_partition(
        df=test_df,
        params=params,
        initial_cash=initial_cash,
        commission=commission,
    )

    return CandidateResult(
        params=params,
        train=train_metrics,
        validation=val_metrics,
        test=test_metrics,
    )


def evaluate_worker_task(payload: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, SMAParams, float, float]) -> CandidateResult:
    """Função top-level serializável (picklable) para execução em pool de processos."""
    train_df, validation_df, test_df, params, initial_cash, commission = payload
    return evaluate_candidate(
        train_df=train_df,
        validation_df=validation_df,
        test_df=test_df,
        params=params,
        initial_cash=initial_cash,
        commission=commission,
    )
