"""Testes unitários para o avaliador de candidatos e fidelidade ao baseline oficial."""

from pathlib import Path
import unittest

from finbot.lab.dataset import load_lab_dataset, split_chronological
from finbot.lab.evaluator import evaluate_candidate, evaluate_partition
from finbot.lab.models import SMAParams

DATASET_PATH = Path("data/backtest/binance_BTCUSDT_5m.json")


class TestLabEvaluator(unittest.TestCase):
    """Bateria de testes para avaliação de métricas e ausência de vazamento de dados."""

    @classmethod
    def setUpClass(cls) -> None:
        _, cls.full_df = load_lab_dataset(DATASET_PATH)
        cls.split = split_chronological(cls.full_df)

    def test_evaluate_partition_matches_backtest_baseline(self) -> None:
        """Avaliar o dataset completo de 500 candles com SMA 5/10 deve replicar o baseline exato."""
        metrics = evaluate_partition(
            df=self.full_df,
            params=SMAParams(short_window=5, long_window=10),
            initial_cash=10000.0,
            commission=0.001,
        )

        self.assertAlmostEqual(metrics.final_equity, 9366.42, places=2)
        self.assertAlmostEqual(metrics.return_pct, -6.34, places=2)
        self.assertAlmostEqual(metrics.buy_and_hold, -0.77, places=2)
        self.assertEqual(metrics.trades, 29)
        self.assertEqual(metrics.wins, 3)
        self.assertEqual(metrics.losses, 26)
        self.assertIsNotNone(metrics.win_rate)
        self.assertAlmostEqual(metrics.win_rate, 10.34, places=2)
        self.assertAlmostEqual(metrics.max_drawdown, -6.34, places=2)
        self.assertIsNotNone(metrics.profit_factor)
        self.assertAlmostEqual(metrics.profit_factor, 0.07, places=2)

    def test_evaluate_candidate_produces_all_partitions(self) -> None:
        """Avaliação de candidato deve preencher Train, Validation e Test com métricas válidas."""
        res = evaluate_candidate(
            train_df=self.split.train_df,
            validation_df=self.split.validation_df,
            test_df=self.split.test_df,
            params=SMAParams(short_window=3, long_window=10),
            initial_cash=10000.0,
            commission=0.001,
        )

        self.assertEqual(res.params.short_window, 3)
        self.assertEqual(res.params.long_window, 10)

        # Treino
        self.assertIsInstance(res.train.final_equity, float)
        self.assertIsInstance(res.train.return_pct, float)

        # Validação
        self.assertIsInstance(res.validation.final_equity, float)
        self.assertIsInstance(res.validation.return_pct, float)

        # Teste (out-of-sample)
        self.assertIsInstance(res.test.final_equity, float)
        self.assertIsInstance(res.test.return_pct, float)

    def test_test_partition_does_not_influence_train_or_validation(self) -> None:
        """Modificações ou dados na partição Test não podem influenciar o resultado de Train ou Val."""
        params = SMAParams(short_window=5, long_window=10)

        res_original = evaluate_candidate(
            train_df=self.split.train_df,
            validation_df=self.split.validation_df,
            test_df=self.split.test_df,
            params=params,
        )

        # Cria partição de teste drasticamente modificada
        altered_test_df = self.split.test_df.copy()
        altered_test_df["Close"] = altered_test_df["Close"] * 10.0

        res_altered = evaluate_candidate(
            train_df=self.split.train_df,
            validation_df=self.split.validation_df,
            test_df=altered_test_df,
            params=params,
        )

        # Train e Val devem ser absolutamente idênticos
        self.assertEqual(res_original.train, res_altered.train)
        self.assertEqual(res_original.validation, res_altered.validation)

        # Teste alterado deve refletir nova performance
        self.assertNotEqual(res_original.test.return_pct, res_altered.test.return_pct)

    def test_candidate_result_to_dict(self) -> None:
        """to_dict deve expor todos os campos necessários para o DataFrame/CSV."""
        res = evaluate_candidate(
            train_df=self.split.train_df,
            validation_df=self.split.validation_df,
            test_df=self.split.test_df,
            params=SMAParams(short_window=5, long_window=15),
        )
        d = res.to_dict()
        self.assertEqual(d["short_window"], 5)
        self.assertEqual(d["long_window"], 15)
        self.assertIn("train_return_pct", d)
        self.assertIn("val_return_pct", d)
        self.assertIn("test_return_pct", d)
        self.assertIn("train_trades", d)


if __name__ == "__main__":
    unittest.main()
