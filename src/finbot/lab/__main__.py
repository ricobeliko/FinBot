"""Ponto de entrada de linha de comando para o FinBot Lab.

Uso:
    python -m finbot.lab [--preset smoke|standard|full] [--workers auto|N] [--confirm-full]
"""

import argparse
from datetime import datetime, timezone
import sys
import time

from finbot.config import get_config
from finbot.lab.dataset import load_lab_dataset, split_chronological
from finbot.lab.grid import PRESET_SMOKE, VALID_PRESETS, generate_sma_grid, validate_preset_execution
from finbot.lab.models import SweepMetadata
from finbot.lab.parallel import determine_worker_count, run_sweep
from finbot.lab.report import export_sweep_results, format_terminal_summary


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m finbot.lab",
        description="FinBot Lab — Laboratório Quantitativo Isolado de Otimização e Screening",
    )
    parser.add_argument(
        "--preset",
        type=str,
        default=PRESET_SMOKE,
        choices=VALID_PRESETS,
        help="Preset de combinações de médias móveis a executar (padrão: smoke)",
    )
    parser.add_argument(
        "--workers",
        type=str,
        default="auto",
        help="Quantidade de processos trabalhadores a alocar ('auto' ou número inteiro >= 1)",
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default="data/backtest/binance_BTCUSDT_5m.json",
        help="Caminho para o snapshot histórico JSON (padrão: dataset oficial)",
    )
    parser.add_argument(
        "--confirm-full",
        action="store_true",
        help="Confirmação mandatória para autorizar a execução do grid FULL de alta intensidade",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=5,
        help="Número de candidatos no ranking a exibir no resumo final do terminal (padrão: 5)",
    )
    parser.add_argument(
        "--sort-by",
        type=str,
        default="return_pct",
        choices=["return_pct", "profit_factor", "win_rate", "max_drawdown"],
        help="Métrica da partição de treino para ordenação do ranking (padrão: return_pct)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/lab/results",
        help="Diretório de destino para exportação de CSV e JSON (padrão: data/lab/results)",
    )

    args = parser.parse_args()

    try:
        validate_preset_execution(args.preset, confirm_full=args.confirm_full)
    except ValueError as err:
        print(f"\n[ERRO DE CONFIGURAÇÃO] {err}", file=sys.stderr)
        sys.exit(1)

    config = get_config()
    num_workers = determine_worker_count(args.workers)

    print("\nCarregando dataset histórico local...")
    try:
        meta_dict, df = load_lab_dataset(args.dataset)
    except FileNotFoundError as err:
        print(f"[ERRO] {err}", file=sys.stderr)
        sys.exit(1)

    split = split_chronological(df)
    grid = generate_sma_grid(preset=args.preset, confirm_full=args.confirm_full)

    print(
        f"Iniciando FinBot Lab | Preset: {args.preset.upper()} | "
        f"Combinações: {len(grid)} | Workers: {num_workers}"
    )

    def on_progress(completed: int, total: int) -> None:
        pct = (completed / total) * 100.0
        sys.stdout.write(f"\rProcessando simulações: {completed}/{total} ({pct:.0f}%)")
        sys.stdout.flush()

    start_perf = time.perf_counter()
    started_at = datetime.now(timezone.utc).isoformat()

    results = run_sweep(
        split=split,
        grid=grid,
        workers=num_workers,
        initial_cash=config.backtest_initial_cash,
        commission=config.backtest_commission,
        progress_callback=on_progress,
    )

    elapsed = time.perf_counter() - start_perf
    completed_at = datetime.now(timezone.utc).isoformat()
    sys.stdout.write("\n")

    metadata = SweepMetadata(
        dataset_path=args.dataset,
        dataset_hash=meta_dict["file_hash"],
        symbol=meta_dict["symbol"],
        timeframe=meta_dict["timeframe"],
        total_candles=len(df),
        train_candles=split.train_count,
        val_candles=split.val_count,
        test_candles=split.test_count,
        preset=args.preset,
        workers=num_workers,
        total_combinations=len(grid),
        initial_cash=config.backtest_initial_cash,
        commission=config.backtest_commission,
        started_at=started_at,
        completed_at=completed_at,
        elapsed_seconds=elapsed,
    )

    csv_path, json_path = export_sweep_results(
        results=results,
        metadata=metadata,
        output_dir=args.output_dir,
    )

    summary = format_terminal_summary(
        metadata=metadata,
        results=results,
        csv_path=csv_path,
        json_path=json_path,
        top_n=args.top,
        sort_by=args.sort_by,
    )
    print(summary)


if __name__ == "__main__":
    main()
