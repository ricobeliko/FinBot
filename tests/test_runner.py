"""Testes unitários determinísticos para o Automated Paper Runner (FASE 7.5).

Valida gravação e leitura do estado de ciclo, cálculo de frescor (RECENT/STALE/UNKNOWN),
persistência entre instâncias, deduplicação e integridade do estado financeiro após falhas.
100% offline e sem dependências de rede.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from logging.handlers import RotatingFileHandler
from pathlib import Path
import tempfile
import unittest

from finbot.config import Config
from finbot.exchange import CandleData
from finbot.logging_setup import setup_logging
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

    def test_09_soak_telemetry_counters(self) -> None:
        """9. Telemetria do Soak Test incrementa total, sucessos, deduplicados e falhas."""
        now = datetime.now(timezone.utc)
        t1 = now.isoformat()
        t2 = (now + timedelta(minutes=1)).isoformat()
        t3 = (now + timedelta(minutes=2)).isoformat()
        t4 = (now + timedelta(minutes=3)).isoformat()

        # Ciclo 1: Sucesso regular (HOLD)
        self.storage.record_cycle_run(result="HOLD", timestamp_iso=t1, is_success=True)
        # Ciclo 2: Deduplicado (NO_NEW_CANDLE)
        self.storage.record_cycle_run(result="NO_NEW_CANDLE", timestamp_iso=t2, is_success=True)
        # Ciclo 3: Falha de conexão
        self.storage.record_cycle_run(result="ERROR", timestamp_iso=t3, is_success=False, message="Timeout na Binance")
        # Ciclo 4: Sucesso após recuperação
        self.storage.record_cycle_run(result="BUY_EXECUTED", timestamp_iso=t4, is_success=True)

        info = self.storage.get_last_cycle_info()
        self.assertEqual(info["total_cycles"], 4)
        self.assertEqual(info["successful_cycles"], 3)
        self.assertEqual(info["deduplicated_cycles"], 1)
        self.assertEqual(info["failed_cycles"], 1)
        self.assertEqual(info["last_error"], "Timeout na Binance")
        self.assertEqual(info["last_error_timestamp"], t3)
        self.assertEqual(info["successful_timestamp"], t4)
        self.assertEqual(info["soak_start"], t1)

    def test_10_network_error_preserves_financial_state(self) -> None:
        """10. Erro de rede ou indisponibilidade da exchange não corrompe saldo, posições ou trades."""
        initial_account = self.storage.get_account()
        initial_position = self.storage.get_position()
        initial_trades = self.storage.get_trades_count()
        last_candle_ts = self.storage.get_last_processed_candle_timestamp()

        # Simula registro de falha de rede
        now_iso = datetime.now(timezone.utc).isoformat()
        self.storage.record_cycle_run(
            result="ERROR",
            timestamp_iso=now_iso,
            is_success=False,
            message="Exchange network connection lost",
        )

        # Estado financeiro deve permanecer estritamente idêntico
        post_account = self.storage.get_account()
        post_position = self.storage.get_position()
        post_trades = self.storage.get_trades_count()
        post_candle_ts = self.storage.get_last_processed_candle_timestamp()

        self.assertEqual(post_account.usdt_balance, initial_account.usdt_balance)
        self.assertEqual(post_account.btc_balance, initial_account.btc_balance)
        self.assertEqual(post_position.side, initial_position.side)
        self.assertEqual(post_trades, initial_trades)
        self.assertEqual(post_candle_ts, last_candle_ts)

        info = self.storage.get_last_cycle_info()
        self.assertEqual(info["failed_cycles"], 1)
        self.assertEqual(info["last_error"], "Exchange network connection lost")

    def test_11_recovery_after_network_error(self) -> None:
        """11. Ciclo bem-sucedido após falha de rede restabelece frescor RECENT e acumula telemetria."""
        now = datetime.now(timezone.utc)
        error_ts = (now - timedelta(minutes=5)).isoformat()
        self.storage.record_cycle_run(
            result="ERROR",
            timestamp_iso=error_ts,
            is_success=False,
            message="DNS resolution failed",
        )

        info_err = self.storage.get_last_cycle_info()
        self.assertEqual(info_err["failed_cycles"], 1)
        self.assertEqual(info_err["successful_cycles"], 0)

        # Rede recuperada: ciclo bem sucedido
        success_ts = now.isoformat()
        self.storage.record_cycle_run(
            result="HOLD",
            timestamp_iso=success_ts,
            is_success=True,
            message="Estratégia executada",
        )

        info_succ = self.storage.get_last_cycle_info()
        self.assertEqual(info_succ["total_cycles"], 2)
        self.assertEqual(info_succ["successful_cycles"], 1)
        self.assertEqual(info_succ["failed_cycles"], 1)
        self.assertEqual(info_succ["successful_timestamp"], success_ts)

        freshness, elapsed = calculate_runner_freshness(info_succ["timestamp"], current_time_iso=success_ts)
        self.assertEqual(freshness, "RECENT")
        self.assertAlmostEqual(elapsed, 0.0, delta=1.0)

    def test_12_rotating_file_handler_configuration(self) -> None:
        """12. O logger configura RotatingFileHandler com limite de 5MB e 3 backups."""
        test_log_path = Path(self.tmp_dir.name) / "test_rotating.log"
        logger = setup_logging(log_level="INFO", log_file=str(test_log_path))
        rotating_handlers = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]
        self.assertTrue(len(rotating_handlers) >= 1)
        handler = rotating_handlers[0]
        self.assertEqual(handler.maxBytes, 5 * 1024 * 1024)
        self.assertEqual(handler.backupCount, 3)


if __name__ == "__main__":
    unittest.main()
