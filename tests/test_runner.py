"""Testes unitários determinísticos para o Automated Paper Runner (FASE 7.5).

Valida gravação e leitura do estado de ciclo, cálculo de frescor (RECENT/STALE/UNKNOWN),
persistência entre instâncias, deduplicação e integridade do estado financeiro após falhas.
100% offline e sem dependências de rede.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from finbot.config import Config
from finbot.exchange import CandleData
from finbot.metrics import calculate_runner_freshness
from finbot.paper import execute_paper_cycle
from finbot.storage import PaperAccount, PaperPosition, PaperStorage


def make_candle(
    timestamp_ms: int,
    open_p: float,
    high_p: float,
    low_p: float,
    close_p: float,
    volume: float = 1.0,
) -> CandleData:
    """Helper para fabricação de CandleData determinístico em testes."""
    return CandleData(
        timestamp=timestamp_ms,
        open=open_p,
        high=high_p,
        low=low_p,
        close=close_p,
        volume=volume,
    )


class TestAutomatedPaperRunner(unittest.TestCase):
    """Bateria de testes unitários para a FASE 7.5 (Automated Paper Runner)."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_runner.sqlite3"
        self.storage = PaperStorage(db_path=self.db_path)
        self.storage.init_db(initial_cash=Decimal("10000.00"))
        self.config = Config(
            paper_initial_cash=10000.0,
            paper_trade_notional=100.0,
            paper_commission=0.001,
            paper_db_path=str(self.db_path),
            short_window=2,
            long_window=4,
        )

    def tearDown(self) -> None:
        try:
            self.tmp_dir.cleanup()
        except Exception:
            pass

    def test_01_runner_freshness_recent(self) -> None:
        """1. Ciclo recente (ex: há 30 segundos) deve retornar estado RECENT."""
        now = datetime.now(timezone.utc)
        cycle_dt = now - timedelta(seconds=30)
        cycle_iso = cycle_dt.isoformat()
        now_iso = now.isoformat()

        status, elapsed = calculate_runner_freshness(
            last_cycle_iso=cycle_iso,
            current_time_iso=now_iso,
            threshold_seconds=180,
        )
        self.assertEqual(status, "RECENT")
        self.assertIsNotNone(elapsed)
        self.assertAlmostEqual(elapsed, 30.0, delta=1.0)

    def test_02_runner_freshness_stale(self) -> None:
        """2. Ciclo antigo (ex: há 240 segundos com limite de 180s) deve retornar STALE."""
        now = datetime.now(timezone.utc)
        cycle_dt = now - timedelta(seconds=240)
        cycle_iso = cycle_dt.isoformat()
        now_iso = now.isoformat()

        status, elapsed = calculate_runner_freshness(
            last_cycle_iso=cycle_iso,
            current_time_iso=now_iso,
            threshold_seconds=180,
        )
        self.assertEqual(status, "STALE")
        self.assertIsNotNone(elapsed)
        self.assertAlmostEqual(elapsed, 240.0, delta=1.0)

    def test_03_runner_freshness_unknown(self) -> None:
        """3. Timestamp nulo, vazio ou inválido deve retornar UNKNOWN."""
        self.assertEqual(calculate_runner_freshness(None), ("UNKNOWN", None))
        self.assertEqual(calculate_runner_freshness(""), ("UNKNOWN", None))
        self.assertEqual(calculate_runner_freshness("data-invalida"), ("UNKNOWN", None))

    def test_04_record_cycle_run_success(self) -> None:
        """4. Gravação de ciclo bem-sucedido persiste timestamp, resultado e sucesso."""
        now_iso = datetime.now(timezone.utc).isoformat()
        self.storage.record_cycle_run(
            result="NO_NEW_CANDLE",
            timestamp_iso=now_iso,
            is_success=True,
            message="No new closed candle.",
        )

        info = self.storage.get_last_cycle_info()
        self.assertEqual(info["timestamp"], now_iso)
        self.assertEqual(info["result"], "NO_NEW_CANDLE")
        self.assertEqual(info["successful_timestamp"], now_iso)
        self.assertEqual(info["message"], "No new closed candle.")

    def test_05_record_cycle_run_failure_preserves_last_successful(self) -> None:
        """5. Falha de ciclo atualiza last_cycle mas não sobrescreve last_successful_cycle."""
        success_iso = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        self.storage.record_cycle_run(
            result="HOLD",
            timestamp_iso=success_iso,
            is_success=True,
            message="Sucesso prévio",
        )

        error_iso = datetime.now(timezone.utc).isoformat()
        self.storage.record_cycle_run(
            result="ERROR",
            timestamp_iso=error_iso,
            is_success=False,
            message="Connection timed out",
        )

        info = self.storage.get_last_cycle_info()
        self.assertEqual(info["timestamp"], error_iso)
        self.assertEqual(info["result"], "ERROR")
        self.assertEqual(info["message"], "Connection timed out")
        self.assertEqual(info["successful_timestamp"], success_iso)

    def test_06_cycle_deduplication_updates_cycle_info(self) -> None:
        """6. Executar ciclo repetido no mesmo candle gera NO_NEW_CANDLE e atualiza observabilidade."""
        t0 = 1000000000000
        candles = [
            make_candle(t0 + i * 60000, 100.0, 101.0, 99.0, 100.0)
            for i in range(10)
        ]
        latest_candle = candles[-1]
        now_eval = latest_candle.timestamp + 120000

        # Primeiro ciclo: processa normalmente
        res1 = execute_paper_cycle(
            storage=self.storage,
            config=self.config,
            now_ms=now_eval,
            ticker_override=100.0,
            candles_override=candles,
        )
        self.assertEqual(res1.trade_action, "HOLD")
        info1 = self.storage.get_last_cycle_info()
        self.assertEqual(info1["result"], "HOLD")

        # Segundo ciclo imediato com os mesmos candles: deve ser deduplicado (NO_NEW_CANDLE)
        res2 = execute_paper_cycle(
            storage=self.storage,
            config=self.config,
            now_ms=now_eval + 1000,
            ticker_override=100.0,
            candles_override=candles,
        )
        self.assertEqual(res2.trade_action, "NO_NEW_CANDLE")
        info2 = self.storage.get_last_cycle_info()
        self.assertEqual(info2["result"], "NO_NEW_CANDLE")

        # Saldo e posição devem permanecer intactos
        account = self.storage.get_account()
        self.assertEqual(account.usdt_balance, Decimal("10000.00"))
        self.assertEqual(account.btc_balance, Decimal("0.00000000"))

    def test_07_cycle_info_persists_across_restarts(self) -> None:
        """7. Dados de ciclo persistem no SQLite e são lidos por nova instância de PaperStorage."""
        ts_iso = datetime.now(timezone.utc).isoformat()
        self.storage.record_cycle_run(
            result="BUY_EXECUTED",
            timestamp_iso=ts_iso,
            is_success=True,
            message="Paper BUY executado.",
        )

        # Nova instância do storage apontando para o mesmo banco
        new_storage = PaperStorage(db_path=self.db_path)
        info = new_storage.get_last_cycle_info()
        self.assertEqual(info["timestamp"], ts_iso)
        self.assertEqual(info["result"], "BUY_EXECUTED")
        self.assertEqual(info["successful_timestamp"], ts_iso)

    def test_08_reset_db_clears_runner_state(self) -> None:
        """8. Reset do banco limpa todas as informações do Paper Runner."""
        ts_iso = datetime.now(timezone.utc).isoformat()
        self.storage.record_cycle_run(
            result="HOLD",
            timestamp_iso=ts_iso,
            is_success=True,
            message="HOLD",
        )
        self.storage.reset_db(initial_cash=Decimal("10000.00"))

        info = self.storage.get_last_cycle_info()
        self.assertEqual(info["timestamp"], "")
        self.assertEqual(info["result"], "")
        self.assertEqual(info["successful_timestamp"], "")


if __name__ == "__main__":
    unittest.main()
