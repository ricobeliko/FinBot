"""Testes unitários determinísticos para métricas e dados do Dashboard (FASE 7).

Valida cálculos de performance, patrimônio, P/L não realizado e comportamento com banco vazio.
Zero internet e sem dependência visual direta do Streamlit.
"""

from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from finbot.config import Config
from finbot.metrics import (
    PerformanceMetrics,
    calculate_paper_equity,
    calculate_performance_metrics,
    calculate_unrealized_pnl,
    get_cumulative_pnl_series,
)
from finbot.storage import PaperAccount, PaperPosition, PaperStorage, PaperTrade


class TestDashboardMetrics(unittest.TestCase):
    """Bateria de testes unitários para a FASE 7 (Métricas e Dashboard)."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_dashboard.sqlite3"
        self.storage = PaperStorage(db_path=self.db_path)
        self.storage.init_db(initial_cash=Decimal("10000.00"))
        self.config = Config(
            paper_initial_cash=10000.0,
            paper_trade_notional=100.0,
            paper_commission=0.001,
            paper_db_path=str(self.db_path),
        )

    def tearDown(self) -> None:
        try:
            self.tmp_dir.cleanup()
        except Exception:
            pass

    def test_01_metrics_with_zero_trades(self) -> None:
        """1. Banco vazio com zero trades não divide por zero e retorna métricas neutras."""
        trades: list[PaperTrade] = []
        metrics = calculate_performance_metrics(trades)

        self.assertEqual(metrics.total_trades, 0)
        self.assertEqual(metrics.closed_trades, 0)
        self.assertEqual(metrics.winning_trades, 0)
        self.assertEqual(metrics.losing_trades, 0)
        self.assertEqual(metrics.break_even_trades, 0)
        self.assertEqual(metrics.win_rate_pct, 0.0)
        self.assertEqual(metrics.total_realized_pnl, Decimal("0.00"))
        self.assertEqual(metrics.total_fees, Decimal("0.00"))
        self.assertIsNone(metrics.best_trade_pnl)
        self.assertIsNone(metrics.worst_trade_pnl)

    def test_02_metrics_with_wins_and_losses(self) -> None:
        """2. Cálculo de win rate, fees e melhor/pior trade com operações simuladas."""
        t1 = PaperTrade(
            id=1,
            timestamp="2026-09-26T10:00:00+00:00",
            candle_timestamp=1700000000000,
            symbol="BTC/USDT",
            side="BUY",
            price=Decimal("50000.00"),
            quantity=Decimal("0.002"),
            notional=Decimal("100.00"),
            fee=Decimal("0.10"),
            realized_pnl=None,
        )
        t2 = PaperTrade(
            id=2,
            timestamp="2026-09-26T10:05:00+00:00",
            candle_timestamp=1700000300000,
            symbol="BTC/USDT",
            side="SELL",
            price=Decimal("55000.00"),
            quantity=Decimal("0.002"),
            notional=Decimal("110.00"),
            fee=Decimal("0.11"),
            realized_pnl=Decimal("9.79"),  # Win
            exit_reason="STRATEGY_SIGNAL",
        )
        t3 = PaperTrade(
            id=3,
            timestamp="2026-09-26T10:10:00+00:00",
            candle_timestamp=1700000600000,
            symbol="BTC/USDT",
            side="BUY",
            price=Decimal("55000.00"),
            quantity=Decimal("0.002"),
            notional=Decimal("110.00"),
            fee=Decimal("0.11"),
            realized_pnl=None,
        )
        t4 = PaperTrade(
            id=4,
            timestamp="2026-09-26T10:15:00+00:00",
            candle_timestamp=1700000900000,
            symbol="BTC/USDT",
            side="SELL",
            price=Decimal("53000.00"),
            quantity=Decimal("0.002"),
            notional=Decimal("106.00"),
            fee=Decimal("0.11"),
            realized_pnl=Decimal("-4.22"),  # Loss
            exit_reason="STOP_LOSS",
        )

        metrics = calculate_performance_metrics([t1, t2, t3, t4])

        self.assertEqual(metrics.total_trades, 4)
        self.assertEqual(metrics.closed_trades, 2)
        self.assertEqual(metrics.winning_trades, 1)
        self.assertEqual(metrics.losing_trades, 1)
        self.assertEqual(metrics.win_rate_pct, 50.0)
        self.assertEqual(metrics.total_fees, Decimal("0.43"))
        self.assertEqual(metrics.total_realized_pnl, Decimal("5.57"))
        self.assertEqual(metrics.best_trade_pnl, Decimal("9.79"))
        self.assertEqual(metrics.worst_trade_pnl, Decimal("-4.22"))

    def test_03_paper_equity_calculation(self) -> None:
        """3. Cálculo de equity com e sem posição aberta."""
        account = PaperAccount(
            usdt_balance=Decimal("9900.00"),
            btc_balance=Decimal("0.00200000"),
            updated_at="2026-09-26T10:00:00+00:00",
        )
        # Caso A: Sem posição aberta (NONE)
        pos_none = PaperPosition(
            side="NONE",
            quantity=Decimal("0.00000000"),
            cost_basis=Decimal("0.00"),
            entry_price=Decimal("0.00"),
            entry_timestamp="",
        )
        eq_none = calculate_paper_equity(account, pos_none, current_price=Decimal("50000.00"))
        self.assertEqual(eq_none, Decimal("9900.00"))

        # Caso B: Com posição aberta e preço atual
        pos_long = PaperPosition(
            side="LONG",
            quantity=Decimal("0.00200000"),
            cost_basis=Decimal("100.10"),
            entry_price=Decimal("50000.00"),
            entry_timestamp="2026-09-26T10:00:00+00:00",
        )
        # Preço subiu para 60000.00 USDT -> 0.002 * 60000 = 120.00 USDT
        eq_long = calculate_paper_equity(account, pos_long, current_price=Decimal("60000.00"))
        self.assertEqual(eq_long, Decimal("10020.00"))

        # Caso C: Com posição aberta, mas preço indisponível (offline) -> mantém saldo USDT
        eq_offline = calculate_paper_equity(account, pos_long, current_price=None)
        self.assertEqual(eq_offline, Decimal("9900.00"))

    def test_04_unrealized_pnl_calculation(self) -> None:
        """4. Cálculo de P/L não realizado de posição aberta."""
        pos_long = PaperPosition(
            side="LONG",
            quantity=Decimal("0.00200000"),
            cost_basis=Decimal("100.00"),
            entry_price=Decimal("50000.00"),
            entry_timestamp="2026-09-26T10:00:00+00:00",
        )
        # Preço em 55000.00 (+10% no ativo) -> valor 110.00 USDT -> P/L não realizado +10.00 (+10.0%)
        u_pnl = calculate_unrealized_pnl(pos_long, current_price=Decimal("55000.00"))
        self.assertIsNotNone(u_pnl)
        assert u_pnl is not None
        u_usdt, u_pct = u_pnl
        self.assertEqual(u_usdt, Decimal("10.00"))
        self.assertEqual(u_pct, 10.0)

        # Sem posição aberta -> retorna None
        pos_none = PaperPosition(
            side="NONE",
            quantity=Decimal("0.0"),
            cost_basis=Decimal("0.0"),
            entry_price=Decimal("0.0"),
            entry_timestamp="",
        )
        self.assertIsNone(calculate_unrealized_pnl(pos_none, current_price=Decimal("55000.00")))

    def test_05_cumulative_pnl_series(self) -> None:
        """5. Geração cronológica da série de P/L acumulado para gráficos."""
        # Se lista vazia -> retorna lista vazia
        self.assertEqual(get_cumulative_pnl_series([]), [])

        # Lista com trades em ordem decrescente (como retornado do SQLite)
        t_buy = PaperTrade(1, "2026-09-26T10:00:00+00:00", 1700000, "BTC/USDT", "BUY", Decimal("50000"), Decimal("0.002"), Decimal("100"), Decimal("0.1"), None)
        t_sell1 = PaperTrade(2, "2026-09-26T10:05:00+00:00", 1700300, "BTC/USDT", "SELL", Decimal("55000"), Decimal("0.002"), Decimal("110"), Decimal("0.11"), Decimal("9.79"), "STRATEGY_SIGNAL")
        t_sell2 = PaperTrade(4, "2026-09-26T10:15:00+00:00", 1700900, "BTC/USDT", "SELL", Decimal("53000"), Decimal("0.002"), Decimal("106"), Decimal("0.11"), Decimal("-4.22"), "STOP_LOSS")

        # Invertido: [t_sell2, t_sell1, t_buy]
        trades = [t_sell2, t_sell1, t_buy]
        series = get_cumulative_pnl_series(trades)

        self.assertEqual(len(series), 2)
        # Primeiro ponto cronológico é t_sell1
        self.assertEqual(series[0]["trade_id"], 2)
        self.assertEqual(series[0]["realized_pnl"], 9.79)
        self.assertEqual(series[0]["cumulative_pnl"], 9.79)
        self.assertEqual(series[0]["exit_reason"], "STRATEGY_SIGNAL")

        # Segundo ponto cronológico é t_sell2: 9.79 - 4.22 = 5.57
        self.assertEqual(series[1]["trade_id"], 4)
        self.assertEqual(series[1]["realized_pnl"], -4.22)
        self.assertAlmostEqual(series[1]["cumulative_pnl"], 5.57, places=2)
        self.assertEqual(series[1]["exit_reason"], "STOP_LOSS")

    def test_06_storage_signal_persistence(self) -> None:
        """6. Persistência e consulta do último sinal avaliado no SQLite."""
        self.assertIsNone(self.storage.get_last_signal())

        self.storage.record_signal("BUY", "Golden cross SMA 5/10", "2026-09-26T12:00:00+00:00")
        sig = self.storage.get_last_signal()
        self.assertIsNotNone(sig)
        assert sig is not None
        self.assertEqual(sig["signal"], "BUY")
        self.assertEqual(sig["reason"], "Golden cross SMA 5/10")
        self.assertEqual(sig["timestamp"], "2026-09-26T12:00:00+00:00")

        self.storage.reset_db()
        self.assertIsNone(self.storage.get_last_signal())

    def test_07_fase6_database_compatibility(self) -> None:
        """7. Dados e migrações da FASE 6 continuam 100% legíveis e compatíveis."""
        account = self.storage.get_account()
        pos = self.storage.get_position()
        self.assertEqual(account.usdt_balance, Decimal("10000.00"))
        self.assertEqual(pos.side, "NONE")
        self.assertFalse(self.storage.get_kill_switch())


if __name__ == "__main__":
    unittest.main()
