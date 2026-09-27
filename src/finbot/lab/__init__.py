"""FinBot Lab — Laboratório quantitativo isolado para pesquisa e otimização offline."""

from finbot.lab.dataset import load_lab_dataset, split_chronological
from finbot.lab.evaluator import evaluate_candidate, evaluate_partition
from finbot.lab.grid import generate_sma_grid, validate_preset_execution
from finbot.lab.models import (
    CandidateResult,
    ChronologicalSplit,
    PartitionMetrics,
    SMAParams,
    SplitRatio,
    SweepMetadata,
)
from finbot.lab.parallel import determine_worker_count, run_sweep
from finbot.lab.report import export_sweep_results, results_to_dataframe

__all__ = [
    "CandidateResult",
    "ChronologicalSplit",
    "PartitionMetrics",
    "SMAParams",
    "SplitRatio",
    "SweepMetadata",
    "determine_worker_count",
    "evaluate_candidate",
    "evaluate_partition",
    "export_sweep_results",
    "generate_sma_grid",
    "load_lab_dataset",
    "results_to_dataframe",
    "run_sweep",
    "split_chronological",
    "validate_preset_execution",
]
