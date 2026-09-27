"""Testes para o módulo de Walk-Forward Analysis (WFA) — Fase 7.9C.

Cobre:
1. Criação correta das janelas deslizantes.
2. Ausência de overlap indevido entre TRAIN e TEST.
3. Ordenação temporal estrita dos candles.
4. Seleção exclusivamente pelo TRAIN.
5. TEST alterado não modifica parâmetros selecionados (Anti-Leakage).
6. Reprodutibilidade e determinismo.
7. Estrutura e integridade dos resultados.
8. Persistência dos resultados (CSV e JSON).
9. Integração com o pipeline existente do FinBot Lab.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

try:
    import vectorbt as vbt
    HAS_VBT = True
except ImportError:
    HAS_VBT = False

from finbot.lab.wfa import (
    WFAWindowSlice,
    generate_wfa_windows,
    run_wfa,
    export_wfa_results,
)


def _create_synthetic_candles(n: int = 1500) -> pd.DataFrame:
    """Gera dataframe OHLCV determinístico com oscilação senoidal contínua."""
    dates = pd.date_range("2026-01-01", periods=n, freq="5min")
    x = np.linspace(0, 16 * np.pi, n)
    base_price = 100.0 + 10.0 * np.sin(x)

    df = pd.DataFrame(
        {
            "Open": base_price,
            "High": base_price + 1.0,
            "Low": base_price - 1.0,
            "Close": base_price + 0.2 * np.cos(x),
            "Volume": 1000.0,
        },
        index=dates,
    )
    return df


class TestLabWFA(unittest.TestCase):
    """Testes unitários e de integração do Walk-Forward Analysis."""

    def test_01_generate_wfa_windows_valid_slices(self) -> None:
        """1. Criação correta das fatias de janelas para 10.000 candles."""
        windows = generate_wfa_windows(
            total_candles=10000,
            train_size=4000,
            test_size=1000,
            step_size=1000,
        )
        self.assertEqual(len(windows), 6)

        expected_bounds = [
            (0, 4000, 4000, 5000),
            (1000, 5000, 5000, 6000),
            (2000, 6000, 6000, 7000),
            (3000, 7000, 7000, 8000),
            (4000, 8000, 8000, 9000),
            (5000, 9000, 9000, 10000),
        ]

        for w, (tr_s, tr_e, te_s, te_e) in zip(windows, expected_bounds):
            self.assertEqual(w.train_start, tr_s)
            self.assertEqual(w.train_end, tr_e)
            self.assertEqual(w.test_start, te_s)
            self.assertEqual(w.test_end, te_e)

    def test_02_windows_zero_overlap_and_temporal_order(self) -> None:
        """2 e 3. Ausência de overlap e ordenação temporal rigorosa."""
        windows = generate_wfa_windows(
            total_candles=2500,
            train_size=1000,
            test_size=500,
            step_size=500,
        )
        df = _create_synthetic_candles(2500)

        for w in windows:
            # Índice de corte: train_end deve ser exatamente test_start
            self.assertEqual(w.train_end, w.test_start)
            train_slice = df.iloc[w.train_start : w.train_end]
            test_slice = df.iloc[w.test_start : w.test_end]

            # Verificação estrita de timestamp: max(train) < min(test)
            self.assertLess(train_slice.index[-1], test_slice.index[0])

    def test_03_generate_wfa_windows_invalid_inputs(self) -> None:
        """Validação defensiva de argumentos inválidos na geração de janelas."""
        with self.assertRaises(ValueError):
            generate_wfa_windows(total_candles=1000, train_size=0, test_size=200)
        with self.assertRaises(ValueError):
            generate_wfa_windows(total_candles=1000, train_size=500, test_size=-10)
        with self.assertRaises(ValueError):
            generate_wfa_windows(total_candles=1000, train_size=800, test_size=300)  # soma > total

    @unittest.skipUnless(HAS_VBT, "VectorBT não está disponível neste ambiente")
    def test_04_wfa_selection_uses_only_train(self) -> None:
        """4. Seleção de parâmetros Top N ocorre exclusivamente com dados do TRAIN."""
        df = _create_synthetic_candles(1500)
        grid = [(2, 5), (3, 8), (4, 10)]

        res = run_wfa(
            df=df,
            param_grid=grid,
            train_size=800,
            test_size=300,
            step_size=300,
            top_n=2,
            batch_size=100,
        )

        self.assertGreater(len(res.windows), 0)
        for w in res.windows:
            self.assertEqual(len(w.candidates), 2)
            # O candidato Top 1 da janela deve ter return_pct >= Top 2 no TRAIN
            self.assertGreaterEqual(
                w.candidates[0].train_return_pct,
                w.candidates[1].train_return_pct,
            )

    @unittest.skipUnless(HAS_VBT, "VectorBT não está disponível neste ambiente")
    def test_05_wfa_anti_leakage_test_mutation(self) -> None:
        """5. Mutações drásticas nos dados de TEST não alteram os parâmetros selecionados."""
        df = _create_synthetic_candles(1500)
        grid = [(2, 5), (3, 8), (4, 10), (5, 12)]

        # Execução 1 com dados limpos
        res_original = run_wfa(
            df=df,
            param_grid=grid,
            train_size=800,
            test_size=300,
            step_size=300,
            top_n=2,
            batch_size=100,
        )

        # Criar cópia mutada onde apenas as seções que atuam como teste são alteradas
        mutated_df = df.copy()
        # Modificar do índice 800 em diante (partição de teste da Window 0)
        mutated_df.iloc[800:, mutated_df.columns.get_loc("Close")] *= 10.0
        mutated_df.iloc[800:, mutated_df.columns.get_loc("Open")] *= 10.0

        # Na Window 0, o TRAIN (0:800) permaneceu 100% idêntico
        res_mutated = run_wfa(
            df=mutated_df,
            param_grid=grid,
            train_size=800,
            test_size=300,
            step_size=300,
            top_n=2,
            batch_size=100,
        )

        # Os parâmetros selecionados na Window 0 DEVEM SER 100% IDÊNTICOS
        w0_orig = res_original.windows[0]
        w0_mut = res_mutated.windows[0]

        self.assertEqual(w0_orig.selected_parameters, w0_mut.selected_parameters)
        self.assertEqual(
            w0_orig.top_1_candidate.short_window,
            w0_mut.top_1_candidate.short_window,
        )
        self.assertEqual(
            w0_orig.top_1_candidate.long_window,
            w0_mut.top_1_candidate.long_window,
        )
        self.assertEqual(
            w0_orig.top_1_candidate.train_return_pct,
            w0_mut.top_1_candidate.train_return_pct,
        )

    @unittest.skipUnless(HAS_VBT, "VectorBT não está disponível neste ambiente")
    def test_06_wfa_reproducibility(self) -> None:
        """6. Duas execuções consecutivas produzem resultados idênticos bit a bit."""
        df = _create_synthetic_candles(1500)
        grid = [(2, 6), (3, 9), (4, 12)]

        res1 = run_wfa(
            df=df,
            param_grid=grid,
            train_size=800,
            test_size=300,
            step_size=300,
            top_n=2,
        )
        res2 = run_wfa(
            df=df,
            param_grid=grid,
            train_size=800,
            test_size=300,
            step_size=300,
            top_n=2,
        )

        self.assertEqual(len(res1.windows), len(res2.windows))
        for w1, w2 in zip(res1.windows, res2.windows):
            self.assertEqual(w1.selected_parameters, w2.selected_parameters)
            self.assertEqual(
                w1.top_1_candidate.train_return_pct,
                w2.top_1_candidate.train_return_pct,
            )
            self.assertEqual(
                w1.top_1_candidate.test_return_pct,
                w2.top_1_candidate.test_return_pct,
            )

    @unittest.skipUnless(HAS_VBT, "VectorBT não está disponível neste ambiente")
    def test_07_export_wfa_results(self) -> None:
        """7 e 8. Exportação e persistência correta de CSVs e JSON estruturado."""
        df = _create_synthetic_candles(1500)
        grid = [(2, 5), (3, 8)]

        res = run_wfa(
            df=df,
            param_grid=grid,
            train_size=800,
            test_size=300,
            step_size=300,
            top_n=2,
            dataset_path="synthetic_test.json",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            win_csv, sum_csv, json_file = export_wfa_results(res, output_dir=tmpdir)

            self.assertTrue(win_csv.exists())
            self.assertTrue(sum_csv.exists())
            self.assertTrue(json_file.exists())

            # Validar leitura do CSV de detalhes
            df_win = pd.read_csv(win_csv)
            self.assertIn("window_id", df_win.columns)
            self.assertIn("train_return_pct", df_win.columns)
            self.assertIn("test_return_pct", df_win.columns)
            self.assertIn("oos_degradation", df_win.columns)

            # Validar leitura do CSV de resumo
            df_sum = pd.read_csv(sum_csv)
            self.assertEqual(len(df_sum), len(res.windows))

            # Validar JSON estruturado
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["num_windows"], len(res.windows))
            self.assertIn("aggregate_summary", data)


if __name__ == "__main__":
    unittest.main()
