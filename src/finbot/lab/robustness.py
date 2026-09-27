"""Módulo de Análise de Robustez e Stress Testing do WFA para o FinBot Lab.

FASE 7.9D:
Avalia sistematicamente a sensibilidade dos resultados do Walk-Forward Analysis (WFA)
a variações controladas:
1. Sensibilidade a Custos (Fee Stress: -25%, baseline, +25%, +50%).
2. Perturbação de Parâmetros (Neighborhood Stress: estabilidade da vizinhança 3x3).
3. Sensibilidade ao Top N preservado (Top 5, 10, 20, 50).
4. Sensibilidade Temporal (Variações de Train/Test/Step).
5. Concentração de Resultados e Distribuição por Janela.
6. Estabilidade dos Parâmetros Selecionados.
7. Matriz de Robustez Consolidada.

Metodologia:
- Zero data leakage: dados de teste nunca retroalimentam o treino.
- Análise diagnóstica e descritiva (sem scores proprietários ou classificações mágicas).
- Reutilização estrita das abstrações existentes (wfa.py, hybrid.py, evaluator.py).
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import logging
from pathlib import Path
import time
from typing import Any, Sequence

import pandas as pd
import numpy as np

from finbot.lab.dataset import load_lab_dataset
from finbot.lab.evaluator import evaluate_partition
from finbot.lab.hybrid import generate_extended_sma_grid, run_vectorbt_screening
from finbot.lab.models import SMAParams
from finbot.lab.wfa import (
    WFACandidateResult,
    WFAResult,
    WFAWindowResult,
    export_wfa_results,
    generate_wfa_windows,
    run_wfa,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FeeStressRow:
    """Resultado da sensibilidade de custo para uma taxa específica."""

    scenario: str
    fee: float
    mean_train_return_pct: float
    mean_test_return_pct: float
    mean_oos_degradation: float
    total_oos_trades: int
    positive_windows: int
    negative_windows: int
    mean_test_mdd: float


@dataclass(frozen=True)
class NeighborhoodStressRow:
    """Resultado da análise de vizinhança (plateau vs cliff) para uma janela."""

    window_id: int
    selected_short: int
    selected_long: int
    selected_train_return: float
    selected_test_return: float
    neighbors_count: int
    neighbors_mean_test_return: float
    neighbors_min_test_return: float
    neighbors_max_test_return: float
    neighbors_std_test_return: float
    is_cliff: bool  # True se a vizinhança tiver desempenho drasticamente divergente (>5% de dispersão)


@dataclass(frozen=True)
class TopNStressRow:
    """Resultado da sensibilidade à quantidade de candidatos Top N preservados."""

    top_n: int
    mean_train_return_pct: float
    mean_test_return_pct: float
    median_test_return_pct: float
    total_trades_evaluated: int
    positive_rate_pct: float


@dataclass(frozen=True)
class TemporalStressRow:
    """Resultado da sensibilidade temporal de corte de janelas."""

    scenario: str
    train_size: int
    test_size: int
    step_size: int
    num_windows: int
    mean_train_return_pct: float
    mean_test_return_pct: float
    median_test_return_pct: float
    mean_oos_degradation: float
    total_oos_trades: int
    positive_windows: int
    negative_windows: int


@dataclass(frozen=True)
class RobustnessAnalysisResult:
    """Consolidação estruturada de todos os testes de estresse de robustez."""

    dataset_path: str
    baseline_summary: dict[str, Any]
    fee_stress: list[FeeStressRow]
    neighborhood_stress: list[NeighborhoodStressRow]
    top_n_stress: list[TopNStressRow]
    temporal_stress: list[TemporalStressRow]
    concentration_metrics: dict[str, Any]
    stability_metrics: dict[str, Any]
    elapsed_seconds: float

    def to_dict(self) -> dict[str, Any]:
        """Serializa os resultados em dicionário para exportação JSON."""
        return {
            "dataset_path": self.dataset_path,
            "baseline_summary": self.baseline_summary,
            "fee_stress": [asdict(r) for r in self.fee_stress],
            "neighborhood_stress": [asdict(r) for r in self.neighborhood_stress],
            "top_n_stress": [asdict(r) for r in self.top_n_stress],
            "temporal_stress": [asdict(r) for r in self.temporal_stress],
            "concentration_metrics": self.concentration_metrics,
            "stability_metrics": self.stability_metrics,
            "elapsed_seconds": self.elapsed_seconds,
        }


def evaluate_fee_sensitivity(
    df: pd.DataFrame,
    param_grid: Sequence[tuple[int, int] | SMAParams],
    fees: Sequence[float] = (0.00075, 0.00100, 0.00125, 0.00150),
    train_size: int = 4000,
    test_size: int = 1000,
    step_size: int = 1000,
    top_n: int = 20,
    batch_size: int = 1000,
    baseline_wfa: WFAResult | None = None,
) -> list[FeeStressRow]:
    """1. Avalia o impacto de diferentes níveis de comissão (-25%, baseline, +25%, +50%)."""
    results: list[FeeStressRow] = []

    for fee in fees:
        diff_pct = ((fee - 0.001) / 0.001) * 100.0
        scenario_name = f"Fee {fee:.5f} ({diff_pct:+.0f}%)" if diff_pct != 0 else "Fee 0.00100 (Baseline)"

        # Reutilizar baseline se disponível para fee 0.00100
        if fee == 0.00100 and baseline_wfa is not None:
            wfa_res = baseline_wfa
        else:
            wfa_res = run_wfa(
                df=df,
                param_grid=param_grid,
                train_size=train_size,
                test_size=test_size,
                step_size=step_size,
                top_n=top_n,
                batch_size=batch_size,
                commission=fee,
            )

        agg = wfa_res.aggregate_summary
        top1_test_mdds = [w.top_1_candidate.test_max_drawdown for w in wfa_res.windows]
        mean_mdd = sum(top1_test_mdds) / len(top1_test_mdds) if top1_test_mdds else 0.0

        results.append(
            FeeStressRow(
                scenario=scenario_name,
                fee=fee,
                mean_train_return_pct=agg["mean_top1_train_return_pct"],
                mean_test_return_pct=agg["mean_top1_test_return_pct"],
                mean_oos_degradation=agg["mean_top1_oos_degradation"],
                total_oos_trades=agg["total_top1_oos_trades"],
                positive_windows=agg["positive_oos_windows"],
                negative_windows=agg["negative_oos_windows"],
                mean_test_mdd=mean_mdd,
            )
        )

    return results


def evaluate_parameter_neighborhood(
    df: pd.DataFrame,
    baseline_wfa: WFAResult,
    radius_short: int = 1,
    radius_long: int = 2,
    initial_cash: float = 10000.0,
    commission: float = 0.001,
) -> list[NeighborhoodStressRow]:
    """2. Avalia a vizinhança 3x3 dos parâmetros selecionados para detectar platôs vs falésias (cliffs)."""
    rows: list[NeighborhoodStressRow] = []

    for w in baseline_wfa.windows:
        top1 = w.top_1_candidate
        s_base = top1.short_window
        l_base = top1.long_window

        train_df = df.iloc[w.train_start_idx : w.train_end_idx].copy()
        test_df = df.iloc[w.test_start_idx : w.test_end_idx].copy()

        # Gerar vizinhança 3x3 válida
        short_candidates = [s for s in (s_base - radius_short, s_base, s_base + radius_short) if s >= 2]
        long_candidates = [l for l in (l_base - radius_long, l_base, l_base + radius_long) if l > max(short_candidates)]

        neighbor_test_returns: list[float] = []

        for s_val in short_candidates:
            for l_val in long_candidates:
                if s_val >= l_val:
                    continue
                # Se for o próprio ponto selecionado, podemos usar ou reavaliar
                p = SMAParams(short_window=s_val, long_window=l_val)
                test_res = evaluate_partition(test_df, p, initial_cash=initial_cash, commission=commission)
                neighbor_test_returns.append(test_res.return_pct)

        mean_ret = float(np.mean(neighbor_test_returns)) if neighbor_test_returns else top1.test_return_pct
        min_ret = float(np.min(neighbor_test_returns)) if neighbor_test_returns else top1.test_return_pct
        max_ret = float(np.max(neighbor_test_returns)) if neighbor_test_returns else top1.test_return_pct
        std_ret = float(np.std(neighbor_test_returns)) if neighbor_test_returns else 0.0

        # Considerado falésia (cliff) se o desvio padrão na vizinhança for superior a 3.0% ou amplitude > 6%
        is_cliff = bool((max_ret - min_ret) > 6.0 or std_ret > 3.0)

        rows.append(
            NeighborhoodStressRow(
                window_id=w.window_id,
                selected_short=s_base,
                selected_long=l_base,
                selected_train_return=top1.train_return_pct,
                selected_test_return=top1.test_return_pct,
                neighbors_count=len(neighbor_test_returns),
                neighbors_mean_test_return=mean_ret,
                neighbors_min_test_return=min_ret,
                neighbors_max_test_return=max_ret,
                neighbors_std_test_return=std_ret,
                is_cliff=is_cliff,
            )
        )

    return rows


def evaluate_top_n_sensitivity(
    baseline_wfa: WFAResult,
    levels: Sequence[int] = (5, 10, 20),
) -> list[TopNStressRow]:
    """3. Avalia o comportamento do grupo OOS quando diferentes quantidades de candidatos são preservadas."""
    rows: list[TopNStressRow] = []

    for n in levels:
        all_train_rets: list[float] = []
        all_test_rets: list[float] = []
        all_trades: list[int] = []

        for w in baseline_wfa.windows:
            group = w.candidates[:n]
            for c in group:
                all_train_rets.append(c.train_return_pct)
                all_test_rets.append(c.test_return_pct)
                all_trades.append(c.test_trades)

        mean_train = float(np.mean(all_train_rets)) if all_train_rets else 0.0
        mean_test = float(np.mean(all_test_rets)) if all_test_rets else 0.0
        median_test = float(np.median(all_test_rets)) if all_test_rets else 0.0
        pos_rate = (sum(1 for r in all_test_rets if r > 0) / len(all_test_rets) * 100.0) if all_test_rets else 0.0

        rows.append(
            TopNStressRow(
                top_n=n,
                mean_train_return_pct=mean_train,
                mean_test_return_pct=mean_test,
                median_test_return_pct=median_test,
                total_trades_evaluated=sum(all_trades),
                positive_rate_pct=pos_rate,
            )
        )

    return rows


def evaluate_temporal_sensitivity(
    df: pd.DataFrame,
    param_grid: Sequence[tuple[int, int] | SMAParams],
    top_n: int = 20,
    batch_size: int = 1000,
    baseline_wfa: WFAResult | None = None,
) -> list[TemporalStressRow]:
    """4. Avalia a sensibilidade a configurações de corte temporal de janelas."""
    configs = [
        ("Train 3000 / Test 1000 / Step 1000", 3000, 1000, 1000),
        ("Train 4000 / Test 1000 / Step 1000 (Baseline)", 4000, 1000, 1000),
        ("Train 5000 / Test 1000 / Step 1000", 5000, 1000, 1000),
        ("Train 4000 / Test 500 / Step 500", 4000, 500, 500),
    ]

    rows: list[TemporalStressRow] = []

    for name, tr_s, te_s, st_s in configs:
        if tr_s == 4000 and te_s == 1000 and st_s == 1000 and baseline_wfa is not None:
            wfa_res = baseline_wfa
        else:
            wfa_res = run_wfa(
                df=df,
                param_grid=param_grid,
                train_size=tr_s,
                test_size=te_s,
                step_size=st_s,
                top_n=top_n,
                batch_size=batch_size,
            )

        agg = wfa_res.aggregate_summary
        test_returns = [w.top_1_candidate.test_return_pct for w in wfa_res.windows]
        median_test = float(np.median(test_returns)) if test_returns else 0.0

        rows.append(
            TemporalStressRow(
                scenario=name,
                train_size=tr_s,
                test_size=te_s,
                step_size=st_s,
                num_windows=wfa_res.num_windows,
                mean_train_return_pct=agg["mean_top1_train_return_pct"],
                mean_test_return_pct=agg["mean_top1_test_return_pct"],
                median_test_return_pct=median_test,
                mean_oos_degradation=agg["mean_top1_oos_degradation"],
                total_oos_trades=agg["total_top1_oos_trades"],
                positive_windows=agg["positive_oos_windows"],
                negative_windows=agg["negative_oos_windows"],
            )
        )

    return rows


def analyze_result_concentration(baseline_wfa: WFAResult) -> dict[str, Any]:
    """5. Analisa a dispersão e dependência de poucas janelas positivas."""
    returns = [w.top_1_candidate.test_return_pct for w in baseline_wfa.windows]
    trades = [w.top_1_candidate.test_trades for w in baseline_wfa.windows]

    best_idx = int(np.argmax(returns))
    best_return = returns[best_idx]
    worst_idx = int(np.argmin(returns))
    worst_return = returns[worst_idx]

    # Retorno excluindo a melhor janela (W3)
    returns_without_best = [r for i, r in enumerate(returns) if i != best_idx]
    mean_without_best = float(np.mean(returns_without_best)) if returns_without_best else 0.0

    return {
        "num_windows": len(returns),
        "mean_oos_return": float(np.mean(returns)),
        "median_oos_return": float(np.median(returns)),
        "std_oos_return": float(np.std(returns)),
        "best_window_id": best_idx,
        "best_window_return": best_return,
        "worst_window_id": worst_idx,
        "worst_window_return": worst_return,
        "mean_without_best_window": mean_without_best,
        "is_highly_concentrated": bool((best_return - mean_without_best) > 5.0),
        "returns_by_window": {f"W{i}": r for i, r in enumerate(returns)},
        "trades_by_window": {f"W{i}": t for i, t in enumerate(trades)},
    }


def analyze_parameter_stability(baseline_wfa: WFAResult) -> dict[str, Any]:
    """6. Analisa a consistência e transição de parâmetros entre janelas consecutivas."""
    shorts = [w.top_1_candidate.short_window for w in baseline_wfa.windows]
    longs = [w.top_1_candidate.long_window for w in baseline_wfa.windows]

    consecutive_short_diffs = [abs(shorts[i] - shorts[i - 1]) for i in range(1, len(shorts))]
    consecutive_long_diffs = [abs(longs[i] - longs[i - 1]) for i in range(1, len(longs))]

    unique_pairs = set(zip(shorts, longs))
    repeated_pairs = len(shorts) - len(unique_pairs)

    return {
        "short_min": min(shorts),
        "short_max": max(shorts),
        "short_mean": float(np.mean(shorts)),
        "long_min": min(longs),
        "long_max": max(longs),
        "long_mean": float(np.mean(longs)),
        "unique_combinations": len(unique_pairs),
        "repeated_combinations": repeated_pairs,
        "mean_consecutive_short_delta": float(np.mean(consecutive_short_diffs)) if consecutive_short_diffs else 0.0,
        "mean_consecutive_long_delta": float(np.mean(consecutive_long_diffs)) if consecutive_long_diffs else 0.0,
        "parameters_by_window": [
            {"window_id": w.window_id, "params": f"SMA({w.top_1_candidate.short_window}, {w.top_1_candidate.long_window})"}
            for w in baseline_wfa.windows
        ],
    }


def run_robustness_analysis(
    df: pd.DataFrame,
    param_grid: Sequence[tuple[int, int] | SMAParams],
    dataset_path: str = "",
    top_n: int = 20,
    batch_size: int = 1000,
    baseline_wfa: WFAResult | None = None,
) -> RobustnessAnalysisResult:
    """Orquestrador completo dos testes de robustez e estresse da Fase 7.9D."""
    start_time = time.time()

    # 1. Obter ou executar o baseline WFA
    if baseline_wfa is None:
        logger.info("Executando baseline WFA (4000/1000/1000, fee 0.001)...")
        baseline_wfa = run_wfa(
            df=df,
            param_grid=param_grid,
            train_size=4000,
            test_size=1000,
            step_size=1000,
            top_n=top_n,
            batch_size=batch_size,
            dataset_path=dataset_path,
        )

    # 2. Teste A: Sensibilidade a Custos
    logger.info("Executando teste de sensibilidade a custos...")
    fee_stress = evaluate_fee_sensitivity(
        df=df,
        param_grid=param_grid,
        baseline_wfa=baseline_wfa,
        top_n=top_n,
        batch_size=batch_size,
    )

    # 3. Teste B: Perturbação de Parâmetros (Neighborhood)
    logger.info("Executando teste de vizinhança de parâmetros...")
    neighborhood_stress = evaluate_parameter_neighborhood(
        df=df,
        baseline_wfa=baseline_wfa,
    )

    # 4. Teste C: Sensibilidade ao Top N
    logger.info("Executando teste de sensibilidade ao Top N...")
    top_n_stress = evaluate_top_n_sensitivity(
        baseline_wfa=baseline_wfa,
        levels=(5, 10, 20),
    )

    # 5. Teste D: Sensibilidade Temporal
    logger.info("Executando teste de sensibilidade temporal...")
    temporal_stress = evaluate_temporal_sensitivity(
        df=df,
        param_grid=param_grid,
        top_n=top_n,
        batch_size=batch_size,
        baseline_wfa=baseline_wfa,
    )

    # 6. Teste E: Concentração dos Resultados
    logger.info("Calculando métricas de concentração...")
    concentration_metrics = analyze_result_concentration(baseline_wfa)

    # 7. Teste F: Estabilidade dos Parâmetros
    logger.info("Calculando métricas de estabilidade de parâmetros...")
    stability_metrics = analyze_parameter_stability(baseline_wfa)

    elapsed = time.time() - start_time

    return RobustnessAnalysisResult(
        dataset_path=dataset_path,
        baseline_summary=baseline_wfa.aggregate_summary,
        fee_stress=fee_stress,
        neighborhood_stress=neighborhood_stress,
        top_n_stress=top_n_stress,
        temporal_stress=temporal_stress,
        concentration_metrics=concentration_metrics,
        stability_metrics=stability_metrics,
        elapsed_seconds=elapsed,
    )


def export_robustness_results(
    result: RobustnessAnalysisResult,
    output_dir: str | Path = "data/lab/results/robustness",
) -> tuple[Path, Path, Path]:
    """Exporta a matriz de robustez em CSVs tabulares e JSON estruturado."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. robustness_summary.csv (Matriz de Experimentos)
    summary_rows: list[dict[str, Any]] = []

    # Fee Stress
    for f in result.fee_stress:
        summary_rows.append({
            "experiment": "Fee Sensitivity",
            "scenario": f.scenario,
            "mean_train_ret_pct": f.mean_train_return_pct,
            "mean_test_ret_pct": f.mean_test_return_pct,
            "median_test_ret_pct": None,
            "oos_degradation": f.mean_oos_degradation,
            "positive_windows": f.positive_windows,
            "negative_windows": f.negative_windows,
            "total_oos_trades": f.total_oos_trades,
            "mean_test_mdd": f.mean_test_mdd,
            "notes": f"Commission: {f.fee:.5f}",
        })

    # Temporal Stress
    for t in result.temporal_stress:
        summary_rows.append({
            "experiment": "Temporal Sensitivity",
            "scenario": t.scenario,
            "mean_train_ret_pct": t.mean_train_return_pct,
            "mean_test_ret_pct": t.mean_test_return_pct,
            "median_test_ret_pct": t.median_test_return_pct,
            "oos_degradation": t.mean_oos_degradation,
            "positive_windows": t.positive_windows,
            "negative_windows": t.negative_windows,
            "total_oos_trades": t.total_oos_trades,
            "mean_test_mdd": None,
            "notes": f"{t.num_windows} windows (Train {t.train_size} / Test {t.test_size})",
        })

    # Top N Stress
    for tn in result.top_n_stress:
        summary_rows.append({
            "experiment": "Top N Selection",
            "scenario": f"Top {tn.top_n} Group",
            "mean_train_ret_pct": tn.mean_train_return_pct,
            "mean_test_ret_pct": tn.mean_test_return_pct,
            "median_test_ret_pct": tn.median_test_return_pct,
            "oos_degradation": tn.mean_test_return_pct - tn.mean_train_return_pct,
            "positive_windows": None,
            "negative_windows": None,
            "total_oos_trades": tn.total_trades_evaluated,
            "mean_test_mdd": None,
            "notes": f"Positive candidate rate: {tn.positive_rate_pct:.1f}%",
        })

    summary_csv = out_dir / "robustness_summary.csv"
    pd.DataFrame(summary_rows).to_csv(summary_csv, index=False)

    # 2. robustness_windows.csv (Detalhes de vizinhança e concentração por janela)
    windows_rows: list[dict[str, Any]] = []
    for n in result.neighborhood_stress:
        windows_rows.append({
            "window_id": n.window_id,
            "selected_params": f"SMA({n.selected_short}, {n.selected_long})",
            "selected_train_return": n.selected_train_return,
            "selected_test_return": n.selected_test_return,
            "neighbors_count": n.neighbors_count,
            "neighbors_mean_test": n.neighbors_mean_test_return,
            "neighbors_min_test": n.neighbors_min_test_return,
            "neighbors_max_test": n.neighbors_max_test_return,
            "neighbors_std_test": n.neighbors_std_test_return,
            "is_cliff": n.is_cliff,
        })

    windows_csv = out_dir / "robustness_windows.csv"
    pd.DataFrame(windows_rows).to_csv(windows_csv, index=False)

    # 3. robustness_results.json
    json_path = out_dir / "robustness_results.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, indent=2)

    return summary_csv, windows_csv, json_path


def format_robustness_terminal_summary(
    result: RobustnessAnalysisResult,
    summary_csv: Path,
    windows_csv: Path,
    json_path: Path,
) -> str:
    """Gera visualização resumida no terminal da matriz de robustez."""
    lines = [
        "================================================================================",
        "FinBot Lab — WFA Robustness & Stress Testing Matrix (Fase 7.9D)",
        "================================================================================",
        f"Dataset:       {result.dataset_path}",
        f"Tempo Total:   {result.elapsed_seconds:.2f} segundos",
        "",
        "Arquivos Exportados:",
        f"  - Matriz de Experimentos: {summary_csv}",
        f"  - Detalhe de Vizinhança:  {windows_csv}",
        f"  - Estrutura JSON:         {json_path}",
        "",
        "1. MATRIZ DE EXPERIMENTOS DE ROBUSTEZ:",
        "Experimento          | Cenário                   | OOS Ret % | OOS Med % | Degradação | Trades | Pos/Neg | Obs",
        "------------------------------------------------------------------------------------------------------------",
    ]

    # Fee Stress
    for f in result.fee_stress:
        lines.append(
            f"Fee Sensitivity      | {f.scenario:<25} | {f.mean_test_return_pct:>+8.2f}% |     --    | "
            f"{f.mean_oos_degradation:>+9.2f}% | {f.total_oos_trades:>6} | {f.positive_windows:>1}/{f.negative_windows:<1}     | Fee={f.fee:.5f}"
        )

    # Temporal Stress
    for t in result.temporal_stress:
        lines.append(
            f"Temporal Sensitivity | {t.scenario:<25} | {t.mean_test_return_pct:>+8.2f}% | {t.median_test_return_pct:>+8.2f}% | "
            f"{t.mean_oos_degradation:>+9.2f}% | {t.total_oos_trades:>6} | {t.positive_windows:>1}/{t.negative_windows:<1}     | {t.num_windows} janelas"
        )

    # Top N Stress
    for tn in result.top_n_stress:
        lines.append(
            f"Top N Selection      | Top {tn.top_n:<21} | {tn.mean_test_return_pct:>+8.2f}% | {tn.median_test_return_pct:>+8.2f}% | "
            f"{tn.mean_test_return_pct - tn.mean_train_return_pct:>+9.2f}% | {tn.total_trades_evaluated:>6} |   --    | Pos={tn.positive_rate_pct:.0f}%"
        )

    lines.extend([
        "------------------------------------------------------------------------------------------------------------",
        "",
        "2. ANÁLISE DE VIZINHANÇA DE PARÂMETROS (Plateau vs Cliff - Vizinhança 3x3):",
        "Window | Parâmetro Base | Test Ret % | Viz. Média | Viz. Mín  | Viz. Máx  | Desvio Padrão | Classificação",
        "------------------------------------------------------------------------------------------------------",
    ])

    for n in result.neighborhood_stress:
        p_str = f"SMA({n.selected_short}, {n.selected_long})"
        cliff_str = "FALÉSIA (Cliff)" if n.is_cliff else "PLATÔ (Estável)"
        lines.append(
            f"W{n.window_id:<5} | {p_str:<14} | {n.selected_test_return:>+9.2f}% | "
            f"{n.neighbors_mean_test_return:>+9.2f}% | {n.neighbors_min_test_return:>+8.2f}% | "
            f"{n.neighbors_max_test_return:>+8.2f}% | {n.neighbors_std_test_return:>12.2f}% | {cliff_str}"
        )

    c = result.concentration_metrics
    s = result.stability_metrics

    lines.extend([
        "------------------------------------------------------------------------------------------------------",
        "",
        "3. CONCENTRAÇÃO E DISTRIBUIÇÃO DOS RESULTADOS:",
        f"  - Média OOS:                     {c['mean_oos_return']:>+8.2f}%",
        f"  - Mediana OOS:                   {c['median_oos_return']:>+8.2f}%",
        f"  - Desvio Padrão OOS:             {c['std_oos_return']:>8.2f}%",
        f"  - Melhor Janela (W{c['best_window_id']}):             {c['best_window_return']:>+8.2f}%",
        f"  - Pior Janela (W{c['worst_window_id']}):               {c['worst_window_return']:>+8.2f}%",
        f"  - Média OOS sem a Melhor Janela: {c['mean_without_best_window']:>+8.2f}% (Altamente dependente de W3: {c['is_highly_concentrated']})",
        "",
        "4. ESTABILIDADE DOS PARÂMETROS:",
        f"  - Faixa Média Curta (Short):     [{s['short_min']}, {s['short_max']}] (Média: {s['short_mean']:.1f})",
        f"  - Faixa Média Longa (Long):      [{s['long_min']}, {s['long_max']}] (Média: {s['long_mean']:.1f})",
        f"  - Combinações Únicas:            {s['unique_combinations']} de 6 janelas ({s['repeated_combinations']} pares repetidos)",
        f"  - Delta Médio Short Consecutivo: {s['mean_consecutive_short_delta']:.2f}",
        f"  - Delta Médio Long Consecutivo:  {s['mean_consecutive_long_delta']:.2f}",
        "",
        "NOTA METODOLÓGICA:",
        "- Esta análise é puramente descritiva e diagnóstica. Não cria 'score mágico' nem escolhe estratégias.",
        "- O conjunto OOS permaneceu estritamente isolado sem retroalimentação para seleção.",
        "================================================================================",
    ])

    return "\n".join(lines)


def load_wfa_results(json_path: str | Path) -> WFAResult:
    """Reconstitui objeto WFAResult a partir de JSON exportado."""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    windows: list[WFAWindowResult] = []
    for w in data["windows"]:
        candidates = [WFACandidateResult(**c) for c in w["candidates"]]
        top1 = WFACandidateResult(**w["top_1_candidate"])
        windows.append(
            WFAWindowResult(
                window_id=w["window_id"],
                train_start_idx=w["train_start_idx"],
                train_end_idx=w["train_end_idx"],
                test_start_idx=w["test_start_idx"],
                test_end_idx=w["test_end_idx"],
                train_start_time=w["train_start_time"],
                train_end_time=w["train_end_time"],
                test_start_time=w["test_start_time"],
                test_end_time=w["test_end_time"],
                selected_parameters=w["selected_parameters"],
                top_1_candidate=top1,
                candidates=candidates,
            )
        )

    return WFAResult(
        dataset_path=data["dataset_path"],
        total_candles=data["total_candles"],
        train_size=data["train_size"],
        test_size=data["test_size"],
        step_size=data["step_size"],
        num_windows=data["num_windows"],
        top_n=data["top_n"],
        windows=windows,
        aggregate_summary=data["aggregate_summary"],
        elapsed_seconds=data["elapsed_seconds"],
    )


def main() -> None:
    """CLI para execução direta da análise de robustez."""
    parser = argparse.ArgumentParser(
        prog="python -m finbot.lab.robustness",
        description="FinBot Lab — WFA Robustness & Stress Testing",
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default="data/backtest/binance_BTCUSDT_5m_10000.json",
        help="Caminho do dataset JSON local congelado",
    )
    parser.add_argument(
        "--max-combos",
        type=int,
        default=1000,
        help="Número máximo de combinações de médias a gerar para o grid (padrão: 1000)",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=20,
        help="Quantidade de candidatos Top N a selecionar por janela (padrão: 20)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/lab/results/robustness",
        help="Diretório de exportação dos resultados (padrão: data/lab/results/robustness)",
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

    # Verificar se já existe resultado do WFA baseline para evitar reprocessamento desnecessário
    baseline_wfa = None
    baseline_json = Path("data/lab/results/wfa/wfa_results.json")
    if baseline_json.exists():
        try:
            print("Carregando resultado WFA baseline pré-existente para reaproveitamento...")
            baseline_wfa = load_wfa_results(baseline_json)
            if baseline_wfa.total_candles != len(df) or baseline_wfa.train_size != 4000:
                baseline_wfa = None
            else:
                print("Baseline WFA carregado com sucesso a partir de wfa_results.json.")
        except Exception as exc:
            logger.warning("Falha ao ler baseline pré-existente: %s", exc)
            baseline_wfa = None

    print("Iniciando bateria de Stress Testing e Robustez...")
    analysis_res = run_robustness_analysis(
        df=df,
        param_grid=grid,
        dataset_path=args.dataset,
        top_n=args.top_n,
        batch_size=1000,
        baseline_wfa=baseline_wfa,
    )

    summary_csv, windows_csv, json_path = export_robustness_results(analysis_res, output_dir=args.output_dir)
    summary_text = format_robustness_terminal_summary(analysis_res, summary_csv, windows_csv, json_path)
    print("\n" + summary_text)


if __name__ == "__main__":
    main()
