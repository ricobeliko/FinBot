"""Módulo do Pipeline Híbrido: VectorBT Screening + FinBot Lab OOS Evaluation.

FASE 7.9B:
1. Screening de alta performance no TRAIN com VectorBT Community (pesquisa/lab isolado).
2. Seleção de candidatos Top N EXCLUSIVAMENTE pelo TRAIN (zero leakage).
3. Reavaliação OOS rigorosa no motor puro do FinBot Lab (Backtesting.py) para
   Train, Validation e Test.
"""

from __future__ import annotations

import logging
from typing import Any, Sequence

import pandas as pd

from finbot.lab.evaluator import evaluate_candidate
from finbot.lab.models import CandidateResult, SMAParams

logger = logging.getLogger(__name__)


def generate_extended_sma_grid(
    short_min: int = 2,
    short_max: int = 100,
    long_min: int = 5,
    long_max: int = 300,
    max_combos: int | None = None,
) -> list[tuple[int, int]]:
    """Gera combinações determinísticas de (short, long) onde short < long."""
    combos: list[tuple[int, int]] = []
    for s in range(short_min, short_max + 1):
        for l in range(max(s + 1, long_min), long_max + 1):
            combos.append((s, l))
            if max_combos and len(combos) >= max_combos:
                return combos
    return combos


def run_vectorbt_screening(
    train_df: pd.DataFrame,
    param_grid: Sequence[tuple[int, int] | SMAParams],
    batch_size: int = 1000,
    initial_cash: float = 10000.0,
    commission: float = 0.001,
) -> list[dict[str, Any]]:
    """Executa screening rápido e vetorizado com VectorBT estritamente sobre TRAIN.

    Alinhamento Semântico Rigoroso com FinBot:
    - Sinal observado no Close da barra t.
    - Sinal deslocado (+1 candle) via shift(1).
    - Execução realizada no preço OPEN da barra t+1.
    - Long-only, spot, 1 posição por vez, initial_cash e fees alinhados.
    """
    try:
        import vectorbt as vbt
    except ImportError as exc:
        raise ImportError(
            "VectorBT não está instalado neste ambiente. "
            "O pipeline de screening do FinBot Lab requer VectorBT (ex.: .venv-research)."
        ) from exc

    # Validação do DataFrame
    if "Close" not in train_df.columns or "Open" not in train_df.columns:
        raise ValueError("DataFrame deve conter as colunas 'Open' e 'Close'.")

    # Normalizar grid
    normalized_grid: list[tuple[int, int]] = []
    for p in param_grid:
        if isinstance(p, SMAParams):
            normalized_grid.append((p.short_window, p.long_window))
        else:
            normalized_grid.append((int(p[0]), int(p[1])))

    train_close = train_df["Close"].astype(float)
    train_open = train_df["Open"].astype(float)

    results: list[dict[str, Any]] = []

    # Processamento em lotes para controle estrito de memória
    num_batches = (len(normalized_grid) + batch_size - 1) // batch_size

    for b in range(num_batches):
        batch = normalized_grid[b * batch_size : (b + 1) * batch_size]
        short_windows = [p[0] for p in batch]
        long_windows = [p[1] for p in batch]

        short_ma = vbt.MA.run(train_close, short_windows, ewm=False)
        long_ma = vbt.MA.run(train_close, long_windows, ewm=False)

        # Semântica FinBot: signal at Close[t] -> shifted by 1 -> executed at Open[t+1]
        entries = short_ma.ma_crossed_above(long_ma).shift(1).fillna(False).astype(bool)
        exits = short_ma.ma_crossed_below(long_ma).shift(1).fillna(False).astype(bool)

        portfolio = vbt.Portfolio.from_signals(
            close=train_open,  # Preço de execução é o OPEN da barra t+1
            entries=entries,
            exits=exits,
            init_cash=initial_cash,
            fees=commission,
            freq="5m",
        )

        returns = portfolio.total_return()
        equities = portfolio.final_value()
        trades = portfolio.trades.count()
        win_rates = portfolio.trades.win_rate()
        profit_factors = portfolio.trades.profit_factor()
        drawdowns = portfolio.max_drawdown()

        for i, (s, l) in enumerate(batch):
            ret_val = float(returns.iloc[i]) if hasattr(returns, "iloc") else float(returns)
            eq_val = float(equities.iloc[i]) if hasattr(equities, "iloc") else float(equities)
            tr_val = int(trades.iloc[i]) if hasattr(trades, "iloc") else int(trades)
            wr_val = float(win_rates.iloc[i]) if hasattr(win_rates, "iloc") else float(win_rates)
            pf_val = float(profit_factors.iloc[i]) if hasattr(profit_factors, "iloc") else float(profit_factors)
            dd_val = float(drawdowns.iloc[i]) if hasattr(drawdowns, "iloc") else float(drawdowns)

            results.append({
                "short_window": s,
                "long_window": l,
                "return_pct": ret_val * 100.0,
                "final_equity": eq_val,
                "trades": tr_val,
                "win_rate": (wr_val * 100.0) if pd.notna(wr_val) else 0.0,
                "profit_factor": pf_val if pd.notna(pf_val) else 0.0,
                "max_drawdown": abs(dd_val * 100.0),
            })

    # Ranking determinístico estritamente sobre TRAIN (mesmo critério composto do FinBot Lab)
    results.sort(
        key=lambda r: (
            r["return_pct"],
            r["profit_factor"],
            r["win_rate"],
            -r["max_drawdown"],
            -r["short_window"],
            -r["long_window"],
        ),
        reverse=True,
    )

    return results


def run_hybrid_pipeline(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    test_df: pd.DataFrame,
    param_grid: Sequence[tuple[int, int] | SMAParams],
    top_n: int = 20,
    batch_size: int = 1000,
    initial_cash: float = 10000.0,
    commission: float = 0.001,
) -> tuple[list[dict[str, Any]], list[CandidateResult]]:
    """Executa o pipeline híbrido completo:

    1. Screening no Train via VectorBT.
    2. Seleção dos Top N baseada estritamente no Train.
    3. Reavaliação no FinBot Lab (Backtesting.py) para Train, Val e Test.
    """
    # Etapa 1: VectorBT Screening sobre Train
    screened_candidates = run_vectorbt_screening(
        train_df=train_df,
        param_grid=param_grid,
        batch_size=batch_size,
        initial_cash=initial_cash,
        commission=commission,
    )

    # Etapa 2: Seleção Top N
    top_candidates = screened_candidates[:top_n]

    # Etapa 3: Reavaliação OOS no FinBot Lab
    oos_evaluations: list[CandidateResult] = []
    for cand in top_candidates:
        params = SMAParams(short_window=cand["short_window"], long_window=cand["long_window"])
        res = evaluate_candidate(
            train_df=train_df,
            validation_df=val_df,
            test_df=test_df,
            params=params,
            initial_cash=initial_cash,
            commission=commission,
        )
        oos_evaluations.append(res)

    return top_candidates, oos_evaluations
