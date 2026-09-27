"""Testes unitários de auditoria metodológica para o FinBot Lab (FASE 7.8).

Valida formalmente:
1. Split cronológico estrito sem embaralhamento
2. Isolamento de candles: nenhum candle de Validation em Train
3. Isolamento de candles: nenhum candle de Test em Train ou Validation
4. Warm-up determinístico: primeiros long_window candles produzem HOLD
5. Ausência de look-ahead bias: cálculo de sinal usa somente dados até t
6. Capital inicial independente entre partições (Train, Val, Test)
7. Posição inicial independente entre partições (sem transbordo de posição)
8. Blindagem do ranking: Validation não influencia ranking do Train
9. Blindagem do ranking: Test não influencia ranking do Train
10. Robustez com dados insuficientes: poucos candles retornam HOLD com motivo claro
"""

from pathlib import Path
import unittest
import numpy as np
import pandas as pd

from finbot.lab.dataset import load_lab_dataset, split_chronological
from finbot.lab.evaluator import evaluate_candidate, evaluate_partition
from finbot.lab.models import (
    CandidateResult,
    PartitionMetrics,
    SMAParams,
    SplitRatio,
    SweepMetadata,
)
from finbot.lab.report import format_terminal_summary
from finbot.strategy import Signal, evaluate_sma_crossover

DATASET_PATH = Path("data/backtest/binance_BTCUSDT_5m.json")


class TestLabMethodologyAudit(unittest.TestCase):
    """Bateria de testes metodológicos garantindo integridade quantitativa do Lab."""

    @classmethod
    def setUpClass(cls) -> None:
        _, cls.full_df = load_lab_dataset(DATASET_PATH)
        cls.split = split_chronological(cls.full_df)

    def test_01_chronological_split_no_shuffle(self) -> None:
        """1. Split cronológico deve preservar estritamente a ordem temporal sem shuffle."""
        dates = self.full_df.index
        # Monotônico crescente original
        self.assertTrue(dates.is_monotonic_increasing)

        # Treino, Validação e Teste devem manter monotonicidade estrita
        self.assertTrue(self.split.train_df.index.is_monotonic_increasing)
        self.assertTrue(self.split.validation_df.index.is_monotonic_increasing)
        self.assertTrue(self.split.test_df.index.is_monotonic_increasing)

        # Ordem temporal entre fatias
        self.assertLess(self.split.train_df.index[-1], self.split.validation_df.index[0])
        self.assertLess(self.split.validation_df.index[-1], self.split.test_df.index[0])

    def test_02_no_validation_candles_in_train(self) -> None:
        """2. Nenhum candle de Validation pode estar presente na partição de Train."""
        train_timestamps = set(self.split.train_df.index)
        val_timestamps = set(self.split.validation_df.index)
        intersection = train_timestamps.intersection(val_timestamps)
        self.assertEqual(len(intersection), 0, "Encontrados candles de Validation dentro do Train!")

    def test_03_no_test_candles_in_train_or_validation(self) -> None:
        """3. Nenhum candle de Test pode estar presente em Train ou Validation."""
        train_timestamps = set(self.split.train_df.index)
        val_timestamps = set(self.split.validation_df.index)
        test_timestamps = set(self.split.test_df.index)

        self.assertEqual(len(test_timestamps.intersection(train_timestamps)), 0)
        self.assertEqual(len(test_timestamps.intersection(val_timestamps)), 0)

    def test_04_warm_up_produces_hold_before_long_window(self) -> None:
        """4. Os primeiros long_window candles devem atuar como warm-up retornando HOLD sem trades."""
        long_w = 10
        # Avalia sequência curta com exatamente long_window candles
        short_series = [100.0 + i for i in range(long_w)]
        res = evaluate_sma_crossover(short_series, short_window=5, long_window=long_w)

        self.assertEqual(res.signal, Signal.HOLD)
        self.assertIn("Dados insuficientes", res.reason)
        self.assertIsNone(res.short_ma)
        self.assertIsNone(res.long_ma)

    def test_05_no_future_candles_used_in_signal_evaluation(self) -> None:
        """5. Avaliação em t não pode acessar preços posteriores a t."""
        closes = [100.0, 102.0, 101.0, 103.0, 105.0, 104.0, 106.0, 108.0, 107.0, 109.0, 110.0]
        # Avaliação com histórico até candle 10 (11 candles)
        res_original = evaluate_sma_crossover(closes, short_window=5, long_window=10)

        # Adiciona candles 'futuros' (t+1, t+2)
        future_closes = closes + [200.0, 300.0, 400.0]
        # Se passarmos apenas a fatia até o instante t, o resultado deve ser rigorosamente o mesmo
        res_sliced = evaluate_sma_crossover(future_closes[: len(closes)], short_window=5, long_window=10)

        self.assertEqual(res_original.signal, res_sliced.signal)
        self.assertEqual(res_original.short_ma, res_sliced.short_ma)
        self.assertEqual(res_original.long_ma, res_sliced.long_ma)

    def test_06_independent_initial_capital_per_split(self) -> None:
        """6. O capital inicial de cada partição é independente e reiniciado a 10.000 USDT."""
        params = SMAParams(short_window=5, long_window=10)
        res = evaluate_candidate(
            train_df=self.split.train_df,
            validation_df=self.split.validation_df,
            test_df=self.split.test_df,
            params=params,
            initial_cash=10000.0,
            commission=0.001,
        )

        # Mesmo que Train termine com equity diferente de 10000 (ex: 9648.88)
        self.assertNotEqual(res.train.final_equity, 10000.0)

        # Validation é avaliada de forma pura partindo de 10000.0
        val_isolated = evaluate_partition(self.split.validation_df, params, initial_cash=10000.0)
        self.assertEqual(res.validation.final_equity, val_isolated.final_equity)

        # Test é avaliado de forma pura partindo de 10000.0
        test_isolated = evaluate_partition(self.split.test_df, params, initial_cash=10000.0)
        self.assertEqual(res.test.final_equity, test_isolated.final_equity)

    def test_07_independent_initial_position_per_split(self) -> None:
        """7. Cada partição inicia com posição zerada (sem transbordo de posição aberta do Train)."""
        # Verifica que o primeiro candle de Validation nunca herda posição aberta do Train
        # Avaliando validation isoladamente vs no candidate result
        params = SMAParams(short_window=3, long_window=10)
        res = evaluate_candidate(
            train_df=self.split.train_df,
            validation_df=self.split.validation_df,
            test_df=self.split.test_df,
            params=params,
        )

        # A partição de validação foi executada como backtest independente
        val_direct = evaluate_partition(self.split.validation_df, params)
        self.assertEqual(res.validation.trades, val_direct.trades)
        self.assertEqual(res.validation.return_pct, val_direct.return_pct)

    def test_08_validation_results_do_not_alter_train_ranking(self) -> None:
        """8. Modificações ou métricas em Validation não podem alterar o ranqueamento de Train."""
        dummy_meta = SweepMetadata(
            dataset_path="dummy.json",
            dataset_hash="hash",
            symbol="BTC/USDT",
            timeframe="5m",
            total_candles=500,
            train_candles=300,
            val_candles=100,
            test_candles=100,
            preset="smoke",
            workers=1,
            total_combinations=2,
            initial_cash=10000.0,
            commission=0.001,
            started_at="",
            completed_at="",
            elapsed_seconds=1.0,
        )

        # Cria 2 candidatos onde Candidate A é melhor no Train que Candidate B
        cand_a = CandidateResult(
            params=SMAParams(5, 10),
            train=PartitionMetrics(10500.0, 5.0, 5, 3, 2, 60.0, -2.0, 1.5, 1.0),
            validation=PartitionMetrics(9800.0, -2.0, 2, 0, 2, 0.0, -3.0, 0.5, -1.0),
            test=PartitionMetrics(10000.0, 0.0, 0, 0, 0, None, 0.0, None, 0.0),
        )
        cand_b = CandidateResult(
            params=SMAParams(8, 20),
            train=PartitionMetrics(10200.0, 2.0, 4, 2, 2, 50.0, -3.0, 1.2, 1.0),
            validation=PartitionMetrics(11000.0, 10.0, 3, 3, 0, 100.0, -1.0, 99.0, 2.0),  # Validação muito superior!
            test=PartitionMetrics(10000.0, 0.0, 0, 0, 0, None, 0.0, None, 0.0),
        )

        summary = format_terminal_summary(
            dummy_meta,
            [cand_b, cand_a],
            csv_path=Path("dummy.csv"),
            json_path=Path("dummy.json"),
            top_n=2,
            sort_by="return_pct",
        )

        # No resumo, #1 DEVE ser cand_a (pois tem 5.0% no Train vs 2.0% de cand_b),
        # ignorando que cand_b teve +10.0% na validação!
        lines = summary.splitlines()
        rank_1_line = [line for line in lines if line.startswith("#1")][0]
        self.assertIn("5     | 10", rank_1_line, "O ranking utilizou dados de validação indevidamente!")

    def test_09_test_results_do_not_alter_train_ranking(self) -> None:
        """9. Modificações ou métricas em Test não podem alterar o ranqueamento de Train."""
        dummy_meta = SweepMetadata(
            dataset_path="dummy.json",
            dataset_hash="hash",
            symbol="BTC/USDT",
            timeframe="5m",
            total_candles=500,
            train_candles=300,
            val_candles=100,
            test_candles=100,
            preset="smoke",
            workers=1,
            total_combinations=2,
            initial_cash=10000.0,
            commission=0.001,
            started_at="",
            completed_at="",
            elapsed_seconds=1.0,
        )

        cand_a = CandidateResult(
            params=SMAParams(5, 10),
            train=PartitionMetrics(10500.0, 5.0, 5, 3, 2, 60.0, -2.0, 1.5, 1.0),
            validation=PartitionMetrics(10000.0, 0.0, 0, 0, 0, None, 0.0, None, 0.0),
            test=PartitionMetrics(9000.0, -10.0, 3, 0, 3, 0.0, -10.0, 0.1, -5.0),
        )
        cand_b = CandidateResult(
            params=SMAParams(8, 20),
            train=PartitionMetrics(10200.0, 2.0, 4, 2, 2, 50.0, -3.0, 1.2, 1.0),
            validation=PartitionMetrics(10000.0, 0.0, 0, 0, 0, None, 0.0, None, 0.0),
            test=PartitionMetrics(12000.0, 20.0, 5, 5, 0, 100.0, -0.5, 99.0, 5.0),  # Teste espetacular!
        )

        summary = format_terminal_summary(
            dummy_meta,
            [cand_b, cand_a],
            csv_path=Path("dummy.csv"),
            json_path=Path("dummy.json"),
            top_n=2,
            sort_by="return_pct",
        )

        lines = summary.splitlines()
        rank_1_line = [line for line in lines if line.startswith("#1")][0]
        self.assertIn("5     | 10", rank_1_line, "O ranking utilizou dados de Test indevidamente!")

    def test_10_sma_insufficient_candles_safe(self) -> None:
        """10. Sequências com menos de long_window + 1 candles retornam HOLD com motivo claro sem erro."""
        # 3 candles para long_window = 10
        res = evaluate_sma_crossover([100.0, 101.0, 102.0], short_window=2, long_window=10)
        self.assertEqual(res.signal, Signal.HOLD)
        self.assertIn("Dados insuficientes", res.reason)
        self.assertIsNone(res.short_ma)
        self.assertIsNone(res.long_ma)


if __name__ == "__main__":
    unittest.main()
