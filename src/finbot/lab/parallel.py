"""Módulo de orquestração paralela e sequencial de simulações para o FinBot Lab.

Utiliza exclusivamente a biblioteca padrão (concurrent.futures.ProcessPoolExecutor),
garantindo execução determinística independente da quantidade de workers alocada.
"""

from collections.abc import Callable
import concurrent.futures
import os
from typing import Sequence

from finbot.lab.evaluator import evaluate_candidate, evaluate_worker_task
from finbot.lab.models import CandidateResult, ChronologicalSplit, SMAParams


def determine_worker_count(workers: str | int | None) -> int:
    """Calcula a quantidade conservadora de workers a utilizar.

    'auto' adota de forma segura max(1, cpu_count - 1), preservando recursos para o SO.
    """
    if workers is None or (isinstance(workers, str) and workers.strip().lower() == "auto"):
        cpus = os.cpu_count() or 1
        return max(1, cpus - 1)

    try:
        count = int(workers)
        return max(1, count)
    except (ValueError, TypeError) as err:
        raise ValueError(
            f"Valor de workers inválido: '{workers}'. Utilize 'auto' ou um número inteiro >= 1."
        ) from err


def run_sweep(
    split: ChronologicalSplit,
    grid: Sequence[SMAParams],
    workers: int = 1,
    initial_cash: float = 10000.0,
    commission: float = 0.001,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[CandidateResult]:
    """Executa a varredura (sweep) de parâmetros de forma sequencial ou paralela.

    Garantias:
    - O resultado retornado preserva a mesma ordem da lista `grid`, garantindo determinismo.
    - Zero comunicação com serviços externos ou bancos operacionais.
    """
    total = len(grid)
    if total == 0:
        return []

    # Execução sequencial para workers=1
    if workers <= 1:
        results: list[CandidateResult] = []
        for idx, params in enumerate(grid):
            res = evaluate_candidate(
                train_df=split.train_df,
                validation_df=split.validation_df,
                test_df=split.test_df,
                params=params,
                initial_cash=initial_cash,
                commission=commission,
            )
            results.append(res)
            if progress_callback:
                progress_callback(idx + 1, total)
        return results

    # Execução paralela via ProcessPoolExecutor nativo
    indexed_results: list[CandidateResult | None] = [None] * total
    payloads = [
        (split.train_df, split.validation_df, split.test_df, params, initial_cash, commission)
        for params in grid
    ]

    completed_count = 0
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        future_to_idx = {
            executor.submit(evaluate_worker_task, payload): idx
            for idx, payload in enumerate(payloads)
        }

        for future in concurrent.futures.as_completed(future_to_idx):
            idx = future_to_idx[future]
            candidate_res = future.result()
            indexed_results[idx] = candidate_res
            completed_count += 1
            if progress_callback:
                progress_callback(completed_count, total)

    # Converte e garante que todos os índices foram preenchidos
    final_results: list[CandidateResult] = [
        r for r in indexed_results if r is not None
    ]
    if len(final_results) != total:
        raise RuntimeError(
            f"Inconsistência na execução paralela: esperados {total} resultados, "
            f"obtidos {len(final_results)}."
        )

    return final_results
