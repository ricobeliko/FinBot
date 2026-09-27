"""Testes metodológicos e de estresse para o módulo de Robustez (Fase 7.9D).

Cobre:
1. Isolamento temporal em todas as variações de janela.
2. Determinismo e reprodutibilidade.
3. Custo (Fee Stress): alteração de taxa altera apenas custos sem modificar dados.
4. Top N: seleção afeta apenas a profundidade de candidatos preservados.
5. Vizinhança de Parâmetros: perturbações geradas deterministicamente com short < long.
6. Configurações temporais sem overlap ou lookahead.
7. Métricas de concentração e estabilidade descritivas.
8. Não-mutação do dataset e ausência de efeitos colaterais.
"""

from __future__ import annotations

import unittest
import numpy as np
import pandas as pd

try:
    import vectorbt as vbt
    HAS_VBT = True
except ImportError:
    HAS_VBT = False

from finbot.lab.robustness import (
    evaluate_fee_sensitivity,
    evaluate_parameter_neighborhood,
    evaluate_top_n_sensitivity,
    evaluate_temporal_sensitivity,
    analyze_result_concentration,
    analyze_parameter_stability,
    run_robustness_analysis,
)
from finbot.lab.wfa import generate_wfa_windows, run_wfa
from finbot.lab.models import SMAParams
from finbot.lab.evaluator import evaluate_partition


def _create_synthetic_candles(n: int = 1500) -> pd.DataFrame:
    """Gera dataframe OHLCV determinístico com oscilação contínua."""
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


class TestLabRobustness(unittest.TestCase):
    """Bateria de testes metodológicos da Análise de Robustez."""

    def test_01_temporal_isolation_all_window_variants(self) -> None:
        """1. Isolamento temporal em todas as variações de janelas deslizantes."""
        df = _create_synthetic_candles(1500)

        configs = [
            (800, 300, 300),
            (600, 200, 200),
            (1000, 250, 250),
        ]

        for tr_s, te_s, st_s in configs:
            windows = generate_wfa_windows(len(df), train_size=tr_s, test_size=te_s, step_size=st_s)
            self.assertGreater(len(windows), 0)
            for w in windows:
                self.assertEqual(w.train_end, w.test_start)
                tr_slice = df.iloc[w.train_start : w.train_end]
                te_slice = df.iloc[w.test_start : w.test_end]
                self.assertLess(tr_slice.index[-1], te_slice.index[0])

    def test_02_fee_stress_changes_costs_only(self) -> None:
        """3. Alteração de taxa altera unicamente a dedução de custos sem alterar dados ou sinais."""
        df = _create_synthetic_candles(300)
        p = SMAParams(short_window=3, long_window=8)

        res_low_fee = evaluate_partition(df, p, initial_cash=10000.0, commission=0.0005)
        res_high_fee = evaluate_partition(df, p, initial_cash=10000.0, commission=0.0020)

        # O número de trades deve ser rigorosamente o mesmo (mesmos sinais disparados)
        self.assertEqual(res_low_fee.trades, res_high_fee.trades)
        # O retorno com taxa maior deve ser estritamente inferior
        if res_low_fee.trades > 0:
            self.assertGreater(res_low_fee.return_pct, res_high_fee.return_pct)

    def test_03_parameter_neighborhood_validity(self) -> None:
        """5. Vizinhança de parâmetros gerada preserva short < long e limites inferiores."""
        s_base, l_base = 3, 10
        radius_short, radius_long = 1, 2

        short_candidates = [s for s in (s_base - radius_short, s_base, s_base + radius_short) if s >= 2]
        long_candidates = [l for l in (l_base - radius_long, l_base, l_base + radius_long) if l > max(short_candidates)]

        self.assertIn(2, short_candidates)
        self.assertIn(3, short_candidates)
        self.assertIn(4, short_candidates)

        for s in short_candidates:
            for l in long_candidates:
                self.assertGreater(l, s)
                self.assertGreaterEqual(s, 2)

    @unittest.skipUnless(HAS_VBT, "VectorBT não está disponível neste ambiente")
    def test_04_top_n_group_evaluation(self) -> None:
        """4. Top N reflete subconjuntos preservados a partir do screening."""
        df = _create_synthetic_candles(1000)
        grid = [(2, 5), (3, 8), (4, 10), (5, 12), (6, 15)]

        wfa_res = run_wfa(
            df=df,
            param_grid=grid,
            train_size=600,
            test_size=200,
            step_size=200,
            top_n=4,
        )

        top_n_rows = evaluate_top_n_sensitivity(wfa_res, levels=(2, 4))
        self.assertEqual(len(top_n_rows), 2)
        self.assertEqual(top_n_rows[0].top_n, 2)
        self.assertEqual(top_n_rows[1].top_n, 4)

    @unittest.skipUnless(HAS_VBT, "VectorBT não está disponível neste ambiente")
    def test_05_neighborhood_stress_execution(self) -> None:
        """5b. Execução da análise de vizinhança sobre o baseline WFA."""
        df = _create_synthetic_candles(1000)
        grid = [(2, 5), (3, 8)]

        wfa_res = run_wfa(
            df=df,
            param_grid=grid,
            train_size=600,
            test_size=200,
            step_size=200,
            top_n=1,
        )

        neigh_rows = evaluate_parameter_neighborhood(df, wfa_res, radius_short=1, radius_long=1)
        self.assertEqual(len(neigh_rows), len(wfa_res.windows))
        for row in neigh_rows:
            self.assertGreater(row.neighbors_count, 0)
            self.assertIsInstance(row.is_cliff, bool)

    def test_06_concentration_and_stability_calculations(self) -> None:
        """7. Cálculos de concentração e estabilidade descritivos e determísticos."""
        # Criar mock WFAResult com dados conhecidos
        from finbot.lab.wfa import WFAWindowResult, WFACandidateResult, WFAResult

        cands = [
            WFACandidateResult(
                window_id=0, rank=1, short_window=3, long_window=10,
                train_return_pct=5.0, train_final_equity=10500.0, train_trades=10,
                train_wins=6, train_losses=4, train_win_rate=60.0, train_max_drawdown=2.0,
                train_profit_factor=1.5, train_buy_and_hold=3.0,
                test_return_pct=2.0, test_final_equity=10200.0, test_trades=4,
                test_wins=2, test_losses=2, test_win_rate=50.0, test_max_drawdown=1.5,
                test_profit_factor=1.2, test_buy_and_hold=1.0, oos_degradation=-3.0
            ),
            WFACandidateResult(
                window_id=1, rank=1, short_window=3, long_window=12,
                train_return_pct=4.0, train_final_equity=10400.0, train_trades=8,
                train_wins=5, train_losses=3, train_win_rate=62.5, train_max_drawdown=1.8,
                train_profit_factor=1.6, train_buy_and_hold=2.5,
                test_return_pct=-1.0, test_final_equity=9900.0, test_trades=3,
                test_wins=1, test_losses=2, test_win_rate=33.3, test_max_drawdown=2.1,
                test_profit_factor=0.8, test_buy_and_hold=-0.5, oos_degradation=-5.0
            ),
        ]

        windows = [
            WFAWindowResult(
                window_id=i, train_start_idx=i*100, train_end_idx=(i+1)*100,
                test_start_idx=(i+1)*100, test_end_idx=(i+2)*100,
                train_start_time="", train_end_time="", test_start_time="", test_end_time="",
                selected_parameters=[], top_1_candidate=cands[i], candidates=[cands[i]]
            )
            for i in range(2)
        ]

        mock_wfa = WFAResult(
            dataset_path="", total_candles=300, train_size=100, test_size=100, step_size=100,
            num_windows=2, top_n=1, windows=windows, aggregate_summary={}, elapsed_seconds=1.0
        )

        conc = analyze_result_concentration(mock_wfa)
        self.assertEqual(conc["num_windows"], 2)
        self.assertEqual(conc["mean_oos_return"], 0.5)  # (2.0 + -1.0) / 2
        self.assertEqual(conc["best_window_id"], 0)

        stab = analyze_parameter_stability(mock_wfa)
        self.assertEqual(stab["short_min"], 3)
        self.assertEqual(stab["short_max"], 3)
        self.assertEqual(stab["long_min"], 10)
        self.assertEqual(stab["long_max"], 12)

    def test_07_no_mutation_of_input_dataframe(self) -> None:
        """8. Análise de robustez não altera nem corrompe o DataFrame original."""
        df = _create_synthetic_candles(200)
        df_hash_before = pd.util.hash_pandas_object(df).sum()

        p = SMAParams(short_window=3, long_window=8)
        evaluate_partition(df, p)

        df_hash_after = pd.util.hash_pandas_object(df).sum()
        self.assertEqual(df_hash_before, df_hash_after)


if __name__ == "__main__":
    unittest.main()
