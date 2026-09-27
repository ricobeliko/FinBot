"""Testes unitários determinísticos para o particionamento de dataset do FinBot Lab."""

from pathlib import Path
import unittest
import pandas as pd

from finbot.lab.dataset import compute_file_hash, load_lab_dataset, split_chronological
from finbot.lab.models import SplitRatio

DATASET_PATH = Path("data/backtest/binance_BTCUSDT_5m.json")


class TestLabDataset(unittest.TestCase):
    """Bateria de testes para divisão cronológica e integridade de dados."""

    def setUp(self) -> None:
        """Cria DataFrame sintético com DatetimeIndex monotônico."""
        dates = pd.date_range("2026-01-01", periods=100, freq="5min", tz="UTC")
        self.dummy_df = pd.DataFrame(
            {
                "Open": [100.0 + i for i in range(100)],
                "High": [105.0 + i for i in range(100)],
                "Low": [95.0 + i for i in range(100)],
                "Close": [102.0 + i for i in range(100)],
                "Volume": [1000.0 for _ in range(100)],
            },
            index=dates,
        )

    def test_chronological_split_preserves_total_count(self) -> None:
        """A soma dos candles de Train, Validation e Test deve ser estritamente igual ao original."""
        split = split_chronological(self.dummy_df, ratio=SplitRatio(train=0.6, validation=0.2, test=0.2))
        self.assertEqual(split.total_count, 100)
        self.assertEqual(split.train_count + split.val_count + split.test_count, 100)
        self.assertEqual(len(split.train_df) + len(split.validation_df) + len(split.test_df), 100)

    def test_chronological_split_zero_overlap(self) -> None:
        """Garante que não há nenhum overlap temporal entre as três partições."""
        split = split_chronological(self.dummy_df, ratio=SplitRatio(train=0.6, validation=0.2, test=0.2))

        train_end = split.train_df.index[-1]
        val_start = split.validation_df.index[0]
        val_end = split.validation_df.index[-1]
        test_start = split.test_df.index[0]

        self.assertLess(train_end, val_start)
        self.assertLess(val_end, test_start)

        # Checagem de interseção nula de índices
        train_idx = set(split.train_df.index)
        val_idx = set(split.validation_df.index)
        test_idx = set(split.test_df.index)

        self.assertEqual(len(train_idx.intersection(val_idx)), 0)
        self.assertEqual(len(val_idx.intersection(test_idx)), 0)
        self.assertEqual(len(train_idx.intersection(test_idx)), 0)

    def test_chronological_split_does_not_mutate_original(self) -> None:
        """Garante que o particionamento cria cópias isoladas e não altera o DataFrame original."""
        original_copy = self.dummy_df.copy()
        split = split_chronological(self.dummy_df)

        # Modifica fatia de treino
        split.train_df.iloc[0, 0] = 999999.0

        # DataFrame original deve permanecer intacto
        pd.testing.assert_frame_equal(self.dummy_df, original_copy)

    def test_invalid_split_ratios(self) -> None:
        """Valida que proporções que não somam 1.0 ou são negativas disparam ValueError."""
        with self.assertRaises(ValueError):
            SplitRatio(train=0.5, validation=0.2, test=0.2)  # Soma 0.9

        with self.assertRaises(ValueError):
            SplitRatio(train=-0.1, validation=0.5, test=0.6)  # Negativo

    def test_insufficient_data_for_split(self) -> None:
        """Rejeita datasets com contagem de candles menor que o mínimo exigido."""
        small_df = self.dummy_df.iloc[:15]
        with self.assertRaises(ValueError):
            split_chronological(small_df, min_candles_per_partition=10)

    def test_load_real_frozen_dataset(self) -> None:
        """Testa o carregamento offline do dataset congelado oficial."""
        self.assertTrue(DATASET_PATH.exists(), "Dataset congelado oficial deve existir")
        meta, df = load_lab_dataset(DATASET_PATH)

        self.assertEqual(len(df), 500)
        self.assertEqual(meta["candle_count"], 500)
        self.assertEqual(meta["symbol"], "BTC/USDT")
        self.assertTrue(len(meta["file_hash"]) == 64)

        # Split no dataset oficial
        split = split_chronological(df)
        self.assertEqual(split.total_count, 500)
        self.assertEqual(split.train_count, 300)
        self.assertEqual(split.val_count, 100)
        self.assertEqual(split.test_count, 100)


if __name__ == "__main__":
    unittest.main()
