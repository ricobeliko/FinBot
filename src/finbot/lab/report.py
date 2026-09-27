"""Módulo de relatórios e exportação tabular/metadados para o FinBot Lab.

Gera arquivos CSV tabulares e JSON estruturados em `data/lab/results/`,
além de formatar saída amigável e resumida para o console.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Sequence
import pandas as pd

from finbot.lab.models import CandidateResult, SweepMetadata


def results_to_dataframe(results: Sequence[CandidateResult]) -> pd.DataFrame:
    """Converte lista de CandidateResult em DataFrame pandas."""
    if not results:
        return pd.DataFrame()
    rows = [r.to_dict() for r in results]
    return pd.DataFrame(rows)


def export_sweep_results(
    results: Sequence[CandidateResult],
    metadata: SweepMetadata,
    output_dir: str | Path = "data/lab/results",
) -> tuple[Path, Path]:
    """Exporta os resultados em arquivo CSV e metadados em arquivo JSON.

    Padrão de nomenclatura:
    `sma_sweep_YYYYMMDD_HHMMSS.csv`
    `sma_sweep_YYYYMMDD_HHMMSS.json`
    """
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    base_name = f"sma_sweep_{timestamp_str}"

    csv_path = out_path / f"{base_name}.csv"
    json_path = out_path / f"{base_name}.json"

    df = results_to_dataframe(results)
    df.to_csv(csv_path, index=False)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(metadata.to_dict(), f, indent=2)

    return csv_path, json_path


def format_terminal_summary(
    metadata: SweepMetadata,
    results: Sequence[CandidateResult],
    csv_path: Path,
    json_path: Path,
    top_n: int = 5,
    sort_by: str = "return_pct",
) -> str:
    """Formata o relatório resumido para apresentação em terminal."""
    # Função auxiliar para ordenação baseada no Train
    def sort_key(c: CandidateResult) -> float:
        if sort_by == "profit_factor":
            return c.train.profit_factor if c.train.profit_factor is not None else -999.0
        elif sort_by == "win_rate":
            return c.train.win_rate if c.train.win_rate is not None else -999.0
        elif sort_by == "max_drawdown":
            return c.train.max_drawdown  # Menor drawdown (menos negativo)
        return c.train.return_pct

    sorted_candidates = sorted(results, key=sort_key, reverse=True)
    top_candidates = sorted_candidates[:top_n]

    train_pct = (metadata.train_candles / metadata.total_candles) * 100.0 if metadata.total_candles > 0 else 0
    val_pct = (metadata.val_candles / metadata.total_candles) * 100.0 if metadata.total_candles > 0 else 0
    test_pct = (metadata.test_candles / metadata.total_candles) * 100.0 if metadata.total_candles > 0 else 0

    lines = [
        "==================================================",
        "FinBot Lab — SMA Parameter Sweep",
        "==================================================",
        "",
        "Dataset:",
        f"{metadata.symbol}",
        f"{metadata.timeframe}",
        f"{metadata.total_candles} candles",
        "",
        "Mode:",
        "EXPLORATORY / ENGINEERING VALIDATION",
        "",
        "Split:",
        f"Train:      {metadata.train_candles} ({train_pct:.1f}%)",
        f"Validation: {metadata.val_candles} ({val_pct:.1f}%)",
        f"Test:       {metadata.test_candles} ({test_pct:.1f}%)",
        "",
        "Preset:",
        f"{metadata.preset.upper()}",
        "",
        "Combinations:",
        f"{metadata.total_combinations}",
        "",
        "Workers:",
        f"{metadata.workers}",
        "",
        "Completed:",
        f"{len(results)} / {metadata.total_combinations}",
        "",
        "Elapsed:",
        f"{metadata.elapsed_seconds:.2f}s",
        "",
        "Results:",
        f"CSV:  {csv_path}",
        f"JSON: {json_path}",
        "",
        f"Top Candidates (Screened by Train {sort_by}):",
        "Rank | Short | Long | Train Ret | Val Ret | Test Ret | Train MDD | Val MDD | Test MDD | Train Trades",
        "--------------------------------------------------------------------------------------------------",
    ]

    for rank, c in enumerate(top_candidates, 1):
        lines.append(
            f"#{rank:<3} | {c.params.short_window:<5} | {c.params.long_window:<4} | "
            f"{c.train.return_pct:>+8.2f}% | {c.validation.return_pct:>+6.2f}% | {c.test.return_pct:>+7.2f}% | "
            f"{c.train.max_drawdown:>8.2f}% | {c.validation.max_drawdown:>6.2f}% | {c.test.max_drawdown:>7.2f}% | "
            f"{c.train.trades:>12}"
        )

    lines.extend([
        "--------------------------------------------------------------------------------------------------",
        "",
        "NOTA METODOLÓGICA:",
        "- O screening acima é ordenado exclusivamente pelo resultado da partição TRAIN.",
        "- Validação e Teste (out-of-sample) são exibidos para diagnóstico de degradação e overfitting.",
        "- O FinBot Lab NÃO promove estratégias automaticamente para o bot operacional.",
        "==================================================",
    ])

    return "\n".join(lines)
