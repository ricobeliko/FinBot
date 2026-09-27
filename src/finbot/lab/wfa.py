"""Módulo de Walk-Forward Analysis (WFA) para o FinBot Lab.

FASE 7.9C:
Implementa análise Walk-Forward estritamente temporal sobre datasets históricos:
- Janelas deslizantes (TRAIN -> TEST / OOS) com step determinístico.
- Seleção de parâmetros Top N realizada EXCLUSIVAMENTE sobre o TRAIN via VectorBT screening.
- Avaliação Out-of-Sample (OOS) realizada independentemente via FinBot Lab (Backtesting.py).
- Zero data leakage: dados futuros não influenciam a seleção.
- Métricas estruturadas preparadas para persistência e futura ingestão em Experience Dataset.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import time
from typing import Any, Sequence

import pandas as pd

from finbot.lab.dataset import load_lab_dataset
from finbot.lab.evaluator import evaluate_partition
from finbot.lab.hybrid import generate_extended_sma_grid, run_vectorbt_screening
from finbot.lab.models import SMAParams

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WFAWindowSlice:
    """Definição dos índices de corte de uma janela do Walk-Forward."""

    window_id: int
    train_start: int
    train_end: int  # índice exclusivo
    test_start: int
    test_end: int   # índice exclusivo

    def __post_init__(self) -> None:
        if self.train_start < 0 or self.train_end <= self.train_start:
            raise ValueError(f"Intervalo de treino inválido: [{self.train_start}:{self.train_end}]")
        if self.test_start < self.train_end:
            raise ValueError(
                f"Data leakage temporal detectado: test_start ({self.test_start}) "
                f"< train_end ({self.train_end})"
            )
        if self.test_end <= self.test_start:
            raise ValueError(f"Intervalo de teste inválido: [{self.test_start}:{self.test_end}]")


@dataclass(frozen=True)
class WFACandidateResult:
    """Resultado da avaliação de um candidato dentro de uma janela WFA."""

    window_id: int
    rank: int
    short_window: int
    long_window: int
    # Métricas Train
    train_return_pct: float
    train_final_equity: float
    train_trades: int
    train_wins: int
    train_losses: int
    train_win_rate: float | None
    train_max_drawdown: float
    train_profit_factor: float | None
    train_buy_and_hold: float
    # Métricas Test (OOS)
    test_return_pct: float
    test_final_equity: float
    test_trades: int
    test_wins: int
    test_losses: int
    test_win_rate: float | None
    test_max_drawdown: float
    test_profit_factor: float | None
    test_buy_and_hold: float
    # Degradação OOS
    oos_degradation: float

    def to_dict(self) -> dict[str, Any]:
        """Serializa em formato de dicionário plano para exportação tabular."""
        return asdict(self)


@dataclass(frozen=True)
class WFAWindowResult:
    """Resultado consolidado de uma janela específica da Walk-Forward Analysis."""

    window_id: int
    train_start_idx: int
    train_end_idx: int
    test_start_idx: int
    test_end_idx: int
    train_start_time: str
    train_end_time: str
    test_start_time: str
    test_end_time: str
    selected_parameters: list[dict[str, Any]]
    top_1_candidate: WFACandidateResult
    candidates: list[WFACandidateResult]

    def to_dict(self) -> dict[str, Any]:
        """Serializa os metadados da janela e candidatos."""
        return {
            "window_id": self.window_id,
            "train_start_idx": self.train_start_idx,
            "train_end_idx": self.train_end_idx,
            "test_start_idx": self.test_start_idx,
            "test_end_idx": self.test_end_idx,
            "train_start_time": self.train_start_time,
            "train_end_time": self.train_end_time,
            "test_start_time": self.test_start_time,
            "test_end_time": self.test_end_time,
            "selected_parameters": self.selected_parameters,
            "top_1_candidate": self.top_1_candidate.to_dict(),
            "candidates": [c.to_dict() for c in self.candidates],
        }


@dataclass(frozen=True)
class WFAResult:
    """Resultado completo e estruturado da Walk-Forward Analysis de todas as janelas."""

    dataset_path: str
    total_candles: int
    train_size: int
    test_size: int
    step_size: int
    num_windows: int
    top_n: int
    windows: list[WFAWindowResult]
    aggregate_summary: dict[str, Any]
    elapsed_seconds: float

    def to_dict(self) -> dict[str, Any]:
        """Serializa o resultado consolidado em formato JSON."""
        return {
            "dataset_path": self.dataset_path,
            "total_candles": self.total_candles,
            "train_size": self.train_size,
            "test_size": self.test_size,
            "step_size": self.step_size,
            "num_windows": self.num_windows,
            "top_n": self.top_n,
            "aggregate_summary": self.aggregate_summary,
            "elapsed_seconds": self.elapsed_seconds,
            "windows": [w.to_dict() for w in self.windows],
        }


def generate_wfa_windows(
    total_candles: int,
    train_size: int = 4000,
    test_size: int = 1000,
    step_size: int = 1000,
) -> list[WFAWindowSlice]:
    """Gera fatias determinísticas de janelas deslizantes (Walk-Forward).

    Garante:
    - train_end == test_start (zero lacuna e zero sobreposição entre treino e teste na janela).
    - Deslocamento de exatamente step_size candles a cada janela.
    - Janela descartada se não houver candles suficientes para cobrir train + test.
    """
    if train_size <= 0:
        raise ValueError(f"train_size deve ser positivo (recebido: {train_size})")
    if test_size <= 0:
        raise ValueError(f"test_size deve ser positivo (recebido: {test_size})")
    if step_size <= 0:
        raise ValueError(f"step_size deve ser positivo (recebido: {step_size})")
    if train_size + test_size > total_candles:
        raise ValueError(
            f"Tamanho total de candles ({total_candles}) é insuficiente para "
            f"train ({train_size}) + test ({test_size})"
        )

    windows: list[WFAWindowSlice] = []
    window_id = 0
    start = 0

    while start + train_size + test_size <= total_candles:
        train_start = start
        train_end = start + train_size
        test_start = train_end
        test_end = test_start + test_size

        windows.append(
            WFAWindowSlice(
                window_id=window_id,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
            )
        )
        window_id += 1
        start += step_size

    return windows


def run_wfa(
    df: pd.DataFrame,
    param_grid: Sequence[tuple[int, int] | SMAParams],
    train_size: int = 4000,
    test_size: int = 1000,
    step_size: int = 1000,
    top_n: int = 20,
    batch_size: int = 1000,
    initial_cash: float = 10000.0,
    commission: float = 0.001,
    dataset_path: str = "",
) -> WFAResult:
    """Executa a Walk-Forward Analysis completa sobre o DataFrame de candles.

    Pipeline por Janela:
    1. Corte temporal estrito de train_df e test_df.
    2. Validação rigorosa de timestamps (max(train_timestamp) < min(test_timestamp)).
    3. Screening VectorBT executado EXCLUSIVAMENTE em train_df.
    4. Seleção dos Top N candidatos ordenados pelas métricas do TRAIN.
    5. Reavaliação OOS de cada candidato no train_df e test_df via FinBot Lab (Backtesting.py).
    6. Consolidação e rastreamento de estabilidade de parâmetros.
    """
    start_time = time.time()
    total_candles = len(df)
    slices = generate_wfa_windows(
        total_candles=total_candles,
        train_size=train_size,
        test_size=test_size,
        step_size=step_size,
    )

    window_results: list[WFAWindowResult] = []

    for sl in slices:
        train_df = df.iloc[sl.train_start : sl.train_end].copy()
        test_df = df.iloc[sl.test_start : sl.test_end].copy()

        # Auditoria estrita anti-leakage temporal
        if len(train_df) > 0 and len(test_df) > 0:
            if train_df.index[-1] >= test_df.index[0]:
                raise ValueError(
                    f"Violação de precedência temporal na Window {sl.window_id}: "
                    f"train_end_time ({train_df.index[-1]}) >= test_start_time ({test_df.index[0]})"
                )

        train_start_str = str(train_df.index[0]) if len(train_df) > 0 else ""
        train_end_str = str(train_df.index[-1]) if len(train_df) > 0 else ""
        test_start_str = str(test_df.index[0]) if len(test_df) > 0 else ""
        test_end_str = str(test_df.index[-1]) if len(test_df) > 0 else ""

        # Etapa A: Screening VectorBT exclusivamente sobre o TRAIN
        screened = run_vectorbt_screening(
            train_df=train_df,
            param_grid=param_grid,
            batch_size=batch_size,
            initial_cash=initial_cash,
            commission=commission,
        )

        # Etapa B: Seleção Top N com base exclusivamente no TRAIN
        selected_screened = screened[:top_n]
        selected_params_meta = [
            {"rank": i + 1, "short_window": c["short_window"], "long_window": c["long_window"]}
            for i, c in enumerate(selected_screened)
        ]

        # Etapa C: Avaliação OOS independente no FinBot Lab (Backtesting.py)
        candidate_results: list[WFACandidateResult] = []
        for rank_idx, cand in enumerate(selected_screened, start=1):
            p = SMAParams(short_window=cand["short_window"], long_window=cand["long_window"])

            train_metrics = evaluate_partition(
                df=train_df,
                params=p,
                initial_cash=initial_cash,
                commission=commission,
            )
            test_metrics = evaluate_partition(
                df=test_df,
                params=p,
                initial_cash=initial_cash,
                commission=commission,
            )

            oos_degradation = test_metrics.return_pct - train_metrics.return_pct

            candidate_results.append(
                WFACandidateResult(
                    window_id=sl.window_id,
                    rank=rank_idx,
                    short_window=p.short_window,
                    long_window=p.long_window,
                    train_return_pct=train_metrics.return_pct,
                    train_final_equity=train_metrics.final_equity,
                    train_trades=train_metrics.trades,
                    train_wins=train_metrics.wins,
                    train_losses=train_metrics.losses,
                    train_win_rate=train_metrics.win_rate,
                    train_max_drawdown=train_metrics.max_drawdown,
                    train_profit_factor=train_metrics.profit_factor,
                    train_buy_and_hold=train_metrics.buy_and_hold,
                    test_return_pct=test_metrics.return_pct,
                    test_final_equity=test_metrics.final_equity,
                    test_trades=test_metrics.trades,
                    test_wins=test_metrics.wins,
                    test_losses=test_metrics.losses,
                    test_win_rate=test_metrics.win_rate,
                    test_max_drawdown=test_metrics.max_drawdown,
                    test_profit_factor=test_metrics.profit_factor,
                    test_buy_and_hold=test_metrics.buy_and_hold,
                    oos_degradation=oos_degradation,
                )
            )

        top_1 = candidate_results[0]

        window_results.append(
            WFAWindowResult(
                window_id=sl.window_id,
                train_start_idx=sl.train_start,
                train_end_idx=sl.train_end,
                test_start_idx=sl.test_start,
                test_end_idx=sl.test_end,
                train_start_time=train_start_str,
                train_end_time=train_end_str,
                test_start_time=test_start_str,
                test_end_time=test_end_str,
                selected_parameters=selected_params_meta,
                top_1_candidate=top_1,
                candidates=candidate_results,
            )
        )

    elapsed = time.time() - start_time

    # Cálculo do resumo agregado
    top1_train_returns = [w.top_1_candidate.train_return_pct for w in window_results]
    top1_test_returns = [w.top_1_candidate.test_return_pct for w in window_results]
    top1_degradations = [w.top_1_candidate.oos_degradation for w in window_results]
    top1_test_trades = [w.top_1_candidate.test_trades for w in window_results]

    param_stability = [
        {
            "window_id": w.window_id,
            "short_window": w.top_1_candidate.short_window,
            "long_window": w.top_1_candidate.long_window,
            "train_return_pct": w.top_1_candidate.train_return_pct,
            "test_return_pct": w.top_1_candidate.test_return_pct,
            "oos_degradation": w.top_1_candidate.oos_degradation,
            "test_trades": w.top_1_candidate.test_trades,
        }
        for w in window_results
    ]

    aggregate_summary = {
        "mean_top1_train_return_pct": sum(top1_train_returns) / len(top1_train_returns) if top1_train_returns else 0.0,
        "mean_top1_test_return_pct": sum(top1_test_returns) / len(top1_test_returns) if top1_test_returns else 0.0,
        "mean_top1_oos_degradation": sum(top1_degradations) / len(top1_degradations) if top1_degradations else 0.0,
        "total_top1_oos_trades": sum(top1_test_trades),
        "positive_oos_windows": sum(1 for r in top1_test_returns if r > 0),
        "negative_oos_windows": sum(1 for r in top1_test_returns if r <= 0),
        "parameter_stability": param_stability,
    }

    return WFAResult(
        dataset_path=dataset_path,
        total_candles=total_candles,
        train_size=train_size,
        test_size=test_size,
        step_size=step_size,
        num_windows=len(window_results),
        top_n=top_n,
        windows=window_results,
        aggregate_summary=aggregate_summary,
        elapsed_seconds=elapsed,
    )


def export_wfa_results(
    wfa_result: WFAResult,
    output_dir: str | Path = "data/lab/results/wfa",
) -> tuple[Path, Path, Path]:
    """Exporta os resultados da Walk-Forward Analysis em CSV e JSON estruturados.

    Gera:
    1. wfa_windows.csv: Todos os candidatos avaliados (Top N) de todas as janelas.
    2. wfa_summary.csv: Resumo por janela focado no candidato Top 1.
    3. wfa_results.json: Estrutura hierárquica completa serializada.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. wfa_windows.csv (todos os candidatos avaliados)
    all_candidates_rows: list[dict[str, Any]] = []
    for w in wfa_result.windows:
        for c in w.candidates:
            row = c.to_dict()
            row["train_start_time"] = w.train_start_time
            row["train_end_time"] = w.train_end_time
            row["test_start_time"] = w.test_start_time
            row["test_end_time"] = w.test_end_time
            all_candidates_rows.append(row)

    windows_csv = out_dir / "wfa_windows.csv"
    pd.DataFrame(all_candidates_rows).to_csv(windows_csv, index=False)

    # 2. wfa_summary.csv (resumo consolidado do Top 1 por janela)
    summary_rows: list[dict[str, Any]] = []
    for w in wfa_result.windows:
        top = w.top_1_candidate
        summary_rows.append({
            "window_id": w.window_id,
            "train_start_idx": w.train_start_idx,
            "train_end_idx": w.train_end_idx,
            "test_start_idx": w.test_start_idx,
            "test_end_idx": w.test_end_idx,
            "train_start_time": w.train_start_time,
            "train_end_time": w.train_end_time,
            "test_start_time": w.test_start_time,
            "test_end_time": w.test_end_time,
            "short_window": top.short_window,
            "long_window": top.long_window,
            "train_return_pct": top.train_return_pct,
            "test_return_pct": top.test_return_pct,
            "oos_degradation": top.oos_degradation,
            "train_trades": top.train_trades,
            "test_trades": top.test_trades,
            "train_win_rate": top.train_win_rate,
            "test_win_rate": top.test_win_rate,
            "train_max_drawdown": top.train_max_drawdown,
            "test_max_drawdown": top.test_max_drawdown,
            "train_profit_factor": top.train_profit_factor,
            "test_profit_factor": top.test_profit_factor,
        })

    summary_csv = out_dir / "wfa_summary.csv"
    pd.DataFrame(summary_rows).to_csv(summary_csv, index=False)

    # 3. wfa_results.json (hierárquico completo)
    json_path = out_dir / "wfa_results.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(wfa_result.to_dict(), f, indent=2)

    return windows_csv, summary_csv, json_path


def format_wfa_terminal_summary(
    wfa_result: WFAResult,
    windows_csv: Path,
    summary_csv: Path,
    json_path: Path,
) -> str:
    """Formata o relatório textual resumido para exibição no terminal."""
    agg = wfa_result.aggregate_summary
    lines = [
        "================================================================================",
        "FinBot Lab — Walk-Forward Analysis (WFA) Summary",
        "================================================================================",
        f"Dataset:       {wfa_result.dataset_path or 'In-Memory DataFrame'} ({wfa_result.total_candles} candles)",
        f"Configuração:  Train = {wfa_result.train_size} candles | Test (OOS) = {wfa_result.test_size} candles | Step = {wfa_result.step_size} candles",
        f"Janelas:       {wfa_result.num_windows} janelas executadas",
        f"Top N:         {wfa_result.top_n} candidatos avaliados por janela",
        f"Tempo Total:   {wfa_result.elapsed_seconds:.2f} segundos",
        "",
        "Resultados Exportados:",
        f"  - Detalhes (Top N por janela): {windows_csv}",
        f"  - Resumo (Top 1 por janela):   {summary_csv}",
        f"  - Estrutura Completa JSON:     {json_path}",
        "",
        "Resumo do Candidato Top 1 por Janela Temporal:",
        "Window | Parâmetros  | Train Ret  | Test (OOS) | Degradação | Train Tr | Test Tr | Train MDD | Test MDD",
        "------------------------------------------------------------------------------------------------",
    ]

    for w in wfa_result.windows:
        top = w.top_1_candidate
        params_str = f"SMA({top.short_window}, {top.long_window})"
        lines.append(
            f"W{w.window_id:<5} | {params_str:<11} | {top.train_return_pct:>+9.2f}% | "
            f"{top.test_return_pct:>+9.2f}% | {top.oos_degradation:>+9.2f}% | "
            f"{top.train_trades:>8} | {top.test_trades:>7} | "
            f"{top.train_max_drawdown:>8.2f}% | {top.test_max_drawdown:>7.2f}%"
        )

    lines.extend([
        "------------------------------------------------------------------------------------------------",
        "",
        "Métricas Agregadas OOS (Top 1):",
        f"  - Retorno Médio no Treino:    {agg['mean_top1_train_return_pct']:>+8.2f}%",
        f"  - Retorno Médio no Teste/OOS: {agg['mean_top1_test_return_pct']:>+8.2f}%",
        f"  - Degradação Média OOS:       {agg['mean_top1_oos_degradation']:>+8.2f}%",
        f"  - Total de Trades no OOS:     {agg['total_top1_oos_trades']:>8}",
        f"  - Janelas OOS Positivas:      {agg['positive_oos_windows']:>8} / {wfa_result.num_windows}",
        f"  - Janelas OOS Negativas:      {agg['negative_oos_windows']:>8} / {wfa_result.num_windows}",
        "",
        "NOTA METODOLÓGICA:",
        "- A seleção dos parâmetros ocorreu exclusivamente na partição de TREINO de cada janela.",
        "- As métricas de TEST (OOS) atuam estritamente como diagnóstico out-of-sample.",
        "- Este relatório reflete evidência empírica das janelas e não constitui garantia de retorno futuro.",
        "================================================================================",
    ])

    return "\n".join(lines)


def main() -> None:
    """CLI para execução direta da Walk-Forward Analysis."""
    parser = argparse.ArgumentParser(
        prog="python -m finbot.lab.wfa",
        description="FinBot Lab — Walk-Forward Analysis (WFA) com Screening Híbrido",
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default="data/backtest/binance_BTCUSDT_5m_10000.json",
        help="Caminho do dataset JSON local congelado",
    )
    parser.add_argument(
        "--train-size",
        type=int,
        default=4000,
        help="Quantidade de candles na janela de treino (padrão: 4000)",
    )
    parser.add_argument(
        "--test-size",
        type=int,
        default=1000,
        help="Quantidade de candles na janela de teste/OOS (padrão: 1000)",
    )
    parser.add_argument(
        "--step-size",
        type=int,
        default=1000,
        help="Passo de avanço temporal entre janelas (padrão: 1000)",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=20,
        help="Quantidade de candidatos Top N a selecionar por janela (padrão: 20)",
    )
    parser.add_argument(
        "--max-combos",
        type=int,
        default=1000,
        help="Número máximo de combinações de médias a gerar para o grid (padrão: 1000)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Tamanho do lote de combinações no screening VectorBT (padrão: 1000)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/lab/results/wfa",
        help="Diretório de exportação dos resultados (padrão: data/lab/results/wfa)",
    )

    args = parser.parse_args()

    print(f"Carregando dataset de {args.dataset}...")
    _, df = load_lab_dataset(args.dataset)

    print(f"Gerando grid determinístico de até {args.max_combos} combinações...")
    grid = generate_extended_sma_grid(
        short_min=2,
        short_max=100,
        long_min=5,
        long_max=300,
        max_combos=args.max_combos,
    )

    print(f"Iniciando Walk-Forward Analysis: {len(df)} candles, Train={args.train_size}, Test={args.test_size}, Step={args.step_size}...")
    wfa_result = run_wfa(
        df=df,
        param_grid=grid,
        train_size=args.train_size,
        test_size=args.test_size,
        step_size=args.step_size,
        top_n=args.top_n,
        batch_size=args.batch_size,
        dataset_path=args.dataset,
    )

    windows_csv, summary_csv, json_path = export_wfa_results(wfa_result, output_dir=args.output_dir)
    summary_text = format_wfa_terminal_summary(wfa_result, windows_csv, summary_csv, json_path)
    print("\n" + summary_text)


if __name__ == "__main__":
    main()
