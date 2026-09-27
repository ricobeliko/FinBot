"""Testes unitários para paralelismo, determinismo estrito e isolamento do FinBot Lab."""

from pathlib import Path
import tempfile
import unittest

from finbot.lab.dataset import load_lab_dataset, split_chronological
from finbot.lab.grid import PRESET_SMOKE, generate_sma_grid
from finbot.lab.models import SweepMetadata
from finbot.lab.parallel import determine_worker_count, run_sweep
from finbot.lab.report import export_sweep_results

DATASET_PATH = Path("data/backtest/binance_BTCUSDT_5m.json")
OPERATIONAL_DB_PATH = Path("data/finbot_paper.sqlite3")


class TestLabParallel(unittest.TestCase):
    """Bateria de testes para concorrência segura, determinismo e isolamento do bot operacional."""

    @classmethod
    def setUpClass(cls) -> None:
        _, cls.df = load_lab_dataset(DATASET_PATH)
        cls.split = split_chronological(cls.df)
        cls.grid = generate_sma_grid(preset=PRESET_SMOKE)

    def test_determine_worker_count(self) -> None:
        """Valida a resolução de workers ('auto', números inteiros e rejeição de inválidos)."""
        auto_count = determine_worker_count("auto")
        self.assertGreaterEqual(auto_count, 1)

        self.assertEqual(determine_worker_count(1), 1)
        self.assertEqual(determine_worker_count(4), 4)
        self.assertEqual(determine_worker_count("2"), 2)

        with self.assertRaises(ValueError):
            determine_worker_count("invalid_worker_count")

    def test_determinism_workers_1_vs_workers_n(self) -> None:
        """Executar com 1 worker vs 2 workers deve produzir resultados 100% idênticos."""
        results_seq = run_sweep(split=self.split, grid=self.grid, workers=1)
        results_par = run_sweep(split=self.split, grid=self.grid, workers=2)

        self.assertEqual(len(results_seq), len(self.grid))
        self.assertEqual(len(results_par), len(self.grid))

        for idx, (seq, par) in enumerate(zip(results_seq, results_par, strict=True)):
            self.assertEqual(
                seq.params,
                par.params,
                f"Parâmetros diferem no índice {idx}: {seq.params} vs {par.params}",
            )
            # Métricas de Treino
            self.assertEqual(seq.train, par.train, f"Treino difere no índice {idx}")
            # Métricas de Validação
            self.assertEqual(seq.validation, par.validation, f"Validação difere no índice {idx}")
            # Métricas de Teste
            self.assertEqual(seq.test, par.test, f"Teste difere no índice {idx}")

    def test_lab_does_not_modify_operational_sqlite(self) -> None:
        """O FinBot Lab nunca deve abrir, alterar ou corromper o banco de dados operacional."""
        if not OPERATIONAL_DB_PATH.exists():
            self.skipTest("Banco operacional não existe nesta máquina de desenvolvimento.")

        db_stat_before = OPERATIONAL_DB_PATH.stat()
        mtime_before = db_stat_before.st_mtime_ns
        size_before = db_stat_before.st_size

        # Executa sweep
        _ = run_sweep(split=self.split, grid=self.grid, workers=1)

        db_stat_after = OPERATIONAL_DB_PATH.stat()
        self.assertEqual(
            mtime_before,
            db_stat_after.st_mtime_ns,
            "O banco de dados operacional data/finbot_paper.sqlite3 foi modificado pelo Lab!",
        )
        self.assertEqual(
            size_before,
            db_stat_after.st_size,
            "O tamanho do banco de dados operacional foi alterado pelo Lab!",
        )

    def test_report_export_generates_valid_csv_and_json(self) -> None:
        """Exportação deve gerar CSV tabular e JSON de metadados íntegros."""
        results = run_sweep(split=self.split, grid=self.grid[:3], workers=1)

        with tempfile.TemporaryDirectory() as tmpdir:
            meta = SweepMetadata(
                dataset_path=str(DATASET_PATH),
                dataset_hash="dummy_hash",
                symbol="BTC/USDT",
                timeframe="5m",
                total_candles=500,
                train_candles=300,
                val_candles=100,
                test_candles=100,
                preset="smoke",
                workers=1,
                total_combinations=3,
                initial_cash=10000.0,
                commission=0.001,
                started_at="2026-09-27T00:00:00Z",
                completed_at="2026-09-27T00:00:01Z",
                elapsed_seconds=1.23,
            )

            csv_path, json_path = export_sweep_results(results, meta, output_dir=tmpdir)
            self.assertTrue(csv_path.exists())
            self.assertTrue(json_path.exists())
            self.assertGreater(csv_path.stat().st_size, 0)
            self.assertGreater(json_path.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
