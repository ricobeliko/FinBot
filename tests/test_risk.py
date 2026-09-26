"""Testes unitários determinísticos para o Risk Engine e persistência (FASE 6).

Todos os testes utilizam banco SQLite temporário e dados sintéticos em memória.
Nenhum teste acessa a internet nem utiliza credenciais ou banco de produção.
Cobre integralmente os 17 cenários exigidos pela FASE 6.
"""

from datetime import datetime, timezone
from decimal import Decimal
import inspect
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from finbot.config import Config
from finbot.exchange import CandleData
from finbot.paper import (
    execute_paper_cycle,
    format_paper_status_report,
)
import finbot.risk as risk_module
from finbot.risk import (
    RiskDecision,
    RiskDecisionCode,
    RiskEngine,
    calculate_daily_realized_loss,
    is_cooldown_active,
)
from finbot.storage import PaperAccount, PaperPosition, PaperStorage, PaperTrade
from finbot.strategy import Signal


def _make_closed_candles(prices: list[float], interval_ms: int = 60000, start_ts: int = 1700000000000) -> list[CandleData]:
    """Gera lista de candles sintéticos para testes."""
    candles = []
    for i, p in enumerate(prices):
        candles.append(
            CandleData(
                timestamp=start_ts + i * interval_ms,
                open=p,
                high=p * 1.01,
                low=p * 0.99,
                close=p,
                volume=10.0,
            )
        )
    return candles


class TestRiskEngine(unittest.TestCase):
    """Bateria de testes unitários para a FASE 6 (Risk Engine Determinístico)."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_risk.sqlite3"
        self.storage = PaperStorage(db_path=self.db_path)
        self.storage.init_db(initial_cash=Decimal("10000.00"))
        self.config = Config(
            paper_initial_cash=10000.0,
            paper_trade_notional=100.0,
            paper_commission=0.001,
            paper_db_path=str(self.db_path),
            paper_timeframe="1m",
            paper_candle_limit=20,
            short_window=5,
            long_window=10,
            risk_max_position_notional=100.0,
            risk_max_daily_loss=50.0,
            risk_cooldown_candles=1,
            risk_stop_loss_pct=0.02,
            risk_kill_switch=False,
        )
        self.risk_engine = RiskEngine(config=self.config)

    def tearDown(self) -> None:
        try:
            self.tmp_dir.cleanup()
        except Exception:
            pass

    def test_01_buy_allowed_within_limits(self) -> None:
        """1. BUY permitido dentro de todos os limites de risco."""
        account = PaperAccount(
            usdt_balance=Decimal("10000.00"),
            btc_balance=Decimal("0.00000000"),
            updated_at="2026-09-26T12:00:00+00:00",
        )
        position = PaperPosition(
            side="NONE",
            quantity=Decimal("0.00000000"),
            cost_basis=Decimal("0.00"),
            entry_price=Decimal("0.00"),
            entry_timestamp="",
        )

        decision = self.risk_engine.evaluate(
            account=account,
            position=position,
            signal=Signal.BUY,
            signal_reason="Golden cross",
            current_price=Decimal("50000.00"),
            candle_timestamp=1700000060000,
            timeframe_ms=60000,
            kill_switch_active=False,
            daily_realized_pnl=Decimal("0.00"),
            last_closed_trade_candle_ts=None,
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.code, RiskDecisionCode.ALLOWED)
        self.assertEqual(decision.action, "BUY")
        self.assertEqual(decision.target_notional, Decimal("100.00"))

    def test_02_buy_blocked_above_max_position(self) -> None:
        """2. BUY bloqueado se já existir posição aberta ou se notional exceder max position."""
        account = PaperAccount(
            usdt_balance=Decimal("9900.00"),
            btc_balance=Decimal("0.00200000"),
            updated_at="2026-09-26T12:00:00+00:00",
        )
        # Caso A: Posição já aberta
        open_position = PaperPosition(
            side="LONG",
            quantity=Decimal("0.00200000"),
            cost_basis=Decimal("100.10"),
            entry_price=Decimal("50000.00"),
            entry_timestamp="2026-09-26T12:00:00+00:00",
        )
        dec_open = self.risk_engine.evaluate(
            account=account,
            position=open_position,
            signal=Signal.BUY,
            signal_reason="Novo sinal",
            current_price=Decimal("50000.00"),
            candle_timestamp=1700000060000,
            timeframe_ms=60000,
            kill_switch_active=False,
            daily_realized_pnl=Decimal("0.00"),
            last_closed_trade_candle_ts=None,
        )
        self.assertFalse(dec_open.allowed)
        self.assertEqual(dec_open.code, RiskDecisionCode.MAX_POSITION)

        # Caso B: Notional da operação acima do max position notional
        cfg_oversize = Config(
            paper_trade_notional=150.0,
            risk_max_position_notional=100.0,
        )
        engine_oversize = RiskEngine(config=cfg_oversize)
        empty_pos = PaperPosition(
            side="NONE",
            quantity=Decimal("0.0"),
            cost_basis=Decimal("0.0"),
            entry_price=Decimal("0.0"),
            entry_timestamp="",
        )
        dec_oversize = engine_oversize.evaluate(
            account=account,
            position=empty_pos,
            signal=Signal.BUY,
            signal_reason="Sinal grande",
            current_price=Decimal("50000.00"),
            candle_timestamp=1700000060000,
            timeframe_ms=60000,
            kill_switch_active=False,
            daily_realized_pnl=Decimal("0.00"),
            last_closed_trade_candle_ts=None,
        )
        self.assertFalse(dec_oversize.allowed)
        self.assertEqual(dec_oversize.code, RiskDecisionCode.MAX_POSITION)

    def test_03_buy_blocked_by_daily_loss(self) -> None:
        """3. BUY bloqueado pelo limite de perda diária realizada."""
        account = PaperAccount(
            usdt_balance=Decimal("9940.00"),
            btc_balance=Decimal("0.00000000"),
            updated_at="2026-09-26T12:00:00+00:00",
        )
        empty_pos = PaperPosition(
            side="NONE",
            quantity=Decimal("0.0"),
            cost_basis=Decimal("0.0"),
            entry_price=Decimal("0.0"),
            entry_timestamp="",
        )

        # Perda acumulada de -50.00 USDT (limite exato atingido)
        dec = self.risk_engine.evaluate(
            account=account,
            position=empty_pos,
            signal=Signal.BUY,
            signal_reason="Sinal",
            current_price=Decimal("50000.00"),
            candle_timestamp=1700000060000,
            timeframe_ms=60000,
            kill_switch_active=False,
            daily_realized_pnl=Decimal("-50.00"),
            last_closed_trade_candle_ts=None,
        )
        self.assertFalse(dec.allowed)
        self.assertEqual(dec.code, RiskDecisionCode.DAILY_LOSS_LIMIT)

    def test_04_sell_allowed_even_after_daily_loss(self) -> None:
        """4. SELL permitido para desarmar posição mesmo se daily loss estiver estourado."""
        account = PaperAccount(
            usdt_balance=Decimal("9900.00"),
            btc_balance=Decimal("0.00200000"),
            updated_at="2026-09-26T12:00:00+00:00",
        )
        open_position = PaperPosition(
            side="LONG",
            quantity=Decimal("0.00200000"),
            cost_basis=Decimal("100.10"),
            entry_price=Decimal("50000.00"),
            entry_timestamp="2026-09-26T12:00:00+00:00",
        )

        dec = self.risk_engine.evaluate(
            account=account,
            position=open_position,
            signal=Signal.SELL,
            signal_reason="Death cross",
            current_price=Decimal("50000.00"),
            candle_timestamp=1700000060000,
            timeframe_ms=60000,
            kill_switch_active=False,
            daily_realized_pnl=Decimal("-65.00"),  # Perda pior que o limite de -50
            last_closed_trade_candle_ts=None,
        )
        self.assertTrue(dec.allowed)
        self.assertEqual(dec.code, RiskDecisionCode.ALLOWED)
        self.assertEqual(dec.action, "SELL")
        self.assertEqual(dec.exit_reason, "STRATEGY_SIGNAL")

    def test_05_stop_loss_closes_position(self) -> None:
        """5. Stop loss defensivo aciona encerramento imediato ao atingir 2% de queda."""
        account = PaperAccount(
            usdt_balance=Decimal("9900.00"),
            btc_balance=Decimal("0.00200000"),
            updated_at="2026-09-26T12:00:00+00:00",
        )
        # Entry em 100.0 USDT
        open_pos = PaperPosition(
            side="LONG",
            quantity=Decimal("1.00000000"),
            cost_basis=Decimal("100.10"),
            entry_price=Decimal("100.00"),
            entry_timestamp="2026-09-26T12:00:00+00:00",
        )

        # Preço caiu para 97.90 (queda de 2.1% >= 2.0%)
        # Mesmo que a estratégia emita BUY ou HOLD, o stop loss prevalece (prioridade 1)
        dec = self.risk_engine.evaluate(
            account=account,
            position=open_pos,
            signal=Signal.HOLD,
            signal_reason="Estratégia neutra",
            current_price=Decimal("97.90"),
            candle_timestamp=1700000060000,
            timeframe_ms=60000,
            kill_switch_active=False,
            daily_realized_pnl=Decimal("0.00"),
            last_closed_trade_candle_ts=None,
        )
        self.assertTrue(dec.allowed)
        self.assertEqual(dec.code, RiskDecisionCode.DEFENSIVE_EXIT_STOP_LOSS)
        self.assertEqual(dec.action, "SELL")
        self.assertEqual(dec.exit_reason, "STOP_LOSS")

    def test_06_stop_loss_calculates_pnl_correctly(self) -> None:
        """6. Stop loss fecha posição em ciclo completo e calcula P/L com taxas corretamente."""
        # 1. Abre posição a preço 100.0 USDT via cruzamento SMA
        buy_prices = [100.0, 100.0, 100.0, 100.0, 100.0, 90.0, 90.0, 90.0, 90.0, 90.0, 200.0]
        buy_candles = _make_closed_candles(buy_prices)
        now_ms_buy = buy_candles[-1].timestamp + 120000

        res_buy = execute_paper_cycle(
            self.storage,
            self.config,
            now_ms=now_ms_buy,
            ticker_override=100.0,
            candles_override=buy_candles,
        )
        self.assertEqual(res_buy.trade_action, "BUY_EXECUTED")
        self.assertEqual(res_buy.position.side, "LONG")
        self.assertEqual(res_buy.position.entry_price, Decimal("100.00"))
        # 100 USDT / 100.0 = 1.0 BTC. Fee: 0.10. Cost basis: 100.10 USDT.

        # 2. Queda de preço para 97.0 USDT (3% abaixo de entry_price 100.0, violando stop de 2%)
        # Fornece candles neutros (que não gerariam SELL por cruzamento)
        neutral_prices = [100.0] * 15
        start_ts = buy_candles[-1].timestamp + 60000
        neutral_candles = _make_closed_candles(neutral_prices, start_ts=start_ts)
        now_ms_sl = neutral_candles[-1].timestamp + 120000

        res_sl = execute_paper_cycle(
            self.storage,
            self.config,
            now_ms=now_ms_sl,
            ticker_override=97.0,  # Preço observado com 3% de queda
            candles_override=neutral_candles,
        )

        self.assertEqual(res_sl.trade_action, "STOP_LOSS_EXECUTED")
        self.assertIsNotNone(res_sl.executed_trade)
        trade = res_sl.executed_trade
        self.assertEqual(trade.side, "SELL")
        self.assertEqual(trade.exit_reason, "STOP_LOSS")
        self.assertEqual(trade.price, Decimal("97.00"))

        # Gross notional: 1.0 * 97.0 = 97.00
        # Fee: 97.00 * 0.001 = 0.097 -> 0.10 USDT
        # Net proceeds: 97.00 - 0.10 = 96.90 USDT
        # Realized P/L: 96.90 - 100.10 = -3.20 USDT
        self.assertEqual(trade.realized_pnl, Decimal("-3.20"))
        self.assertEqual(res_sl.position.side, "NONE")
        self.assertEqual(res_sl.account.btc_balance, Decimal("0.00000000"))
        # Saldo inicial: 10000.00 -> Comprar: 9899.90 -> Vender: 9899.90 + 96.90 = 9996.80 USDT
        self.assertEqual(res_sl.account.usdt_balance, Decimal("9996.80"))

    def test_07_cooldown_blocks_new_buy(self) -> None:
        """7. Cooldown de candles fechados bloqueia novo BUY imediatamente após fechamento."""
        t_close = 1700000060000
        timeframe_ms = 60000
        # Próximo candle imediatamente posterior (elapsed = 1 candle <= 1 cooldown candle)
        t_current = t_close + timeframe_ms

        active = is_cooldown_active(
            last_closed_trade_candle_ts=t_close,
            current_candle_ts=t_current,
            cooldown_candles=1,
            timeframe_ms=timeframe_ms,
        )
        self.assertTrue(active)

        account = PaperAccount(
            usdt_balance=Decimal("10000.00"),
            btc_balance=Decimal("0.0"),
            updated_at="2026-09-26T12:00:00+00:00",
        )
        empty_pos = PaperPosition(
            side="NONE",
            quantity=Decimal("0.0"),
            cost_basis=Decimal("0.0"),
            entry_price=Decimal("0.0"),
            entry_timestamp="",
        )
        dec = self.risk_engine.evaluate(
            account=account,
            position=empty_pos,
            signal=Signal.BUY,
            signal_reason="Golden cross",
            current_price=Decimal("50000.00"),
            candle_timestamp=t_current,
            timeframe_ms=timeframe_ms,
            kill_switch_active=False,
            daily_realized_pnl=Decimal("0.00"),
            last_closed_trade_candle_ts=t_close,
        )
        self.assertFalse(dec.allowed)
        self.assertEqual(dec.code, RiskDecisionCode.COOLDOWN_ACTIVE)

    def test_08_cooldown_expires_correctly(self) -> None:
        """8. Cooldown expira quando número estipulado de candles fechados é superado."""
        t_close = 1700000060000
        timeframe_ms = 60000
        # 2 candles depois (elapsed = 2 candles > 1 cooldown candle)
        t_current = t_close + 2 * timeframe_ms

        active = is_cooldown_active(
            last_closed_trade_candle_ts=t_close,
            current_candle_ts=t_current,
            cooldown_candles=1,
            timeframe_ms=timeframe_ms,
        )
        self.assertFalse(active)

        account = PaperAccount(
            usdt_balance=Decimal("10000.00"),
            btc_balance=Decimal("0.0"),
            updated_at="2026-09-26T12:00:00+00:00",
        )
        empty_pos = PaperPosition(
            side="NONE",
            quantity=Decimal("0.0"),
            cost_basis=Decimal("0.0"),
            entry_price=Decimal("0.0"),
            entry_timestamp="",
        )
        dec = self.risk_engine.evaluate(
            account=account,
            position=empty_pos,
            signal=Signal.BUY,
            signal_reason="Golden cross",
            current_price=Decimal("50000.00"),
            candle_timestamp=t_current,
            timeframe_ms=timeframe_ms,
            kill_switch_active=False,
            daily_realized_pnl=Decimal("0.00"),
            last_closed_trade_candle_ts=t_close,
        )
        self.assertTrue(dec.allowed)
        self.assertEqual(dec.code, RiskDecisionCode.ALLOWED)

    def test_09_kill_switch_blocks_buy(self) -> None:
        """9. Kill switch ativado bloqueia qualquer novo BUY."""
        account = PaperAccount(
            usdt_balance=Decimal("10000.00"),
            btc_balance=Decimal("0.0"),
            updated_at="2026-09-26T12:00:00+00:00",
        )
        empty_pos = PaperPosition(
            side="NONE",
            quantity=Decimal("0.0"),
            cost_basis=Decimal("0.0"),
            entry_price=Decimal("0.0"),
            entry_timestamp="",
        )

        dec = self.risk_engine.evaluate(
            account=account,
            position=empty_pos,
            signal=Signal.BUY,
            signal_reason="Sinal forte",
            current_price=Decimal("50000.00"),
            candle_timestamp=1700000060000,
            timeframe_ms=60000,
            kill_switch_active=True,
            daily_realized_pnl=Decimal("0.00"),
            last_closed_trade_candle_ts=None,
        )
        self.assertFalse(dec.allowed)
        self.assertEqual(dec.code, RiskDecisionCode.KILL_SWITCH_ACTIVE)

    def test_10_kill_switch_does_not_block_exit(self) -> None:
        """10. Kill switch ativo não impede saídas defensivas ou fechamento de posições."""
        account = PaperAccount(
            usdt_balance=Decimal("9900.00"),
            btc_balance=Decimal("0.002"),
            updated_at="2026-09-26T12:00:00+00:00",
        )
        open_pos = PaperPosition(
            side="LONG",
            quantity=Decimal("0.002"),
            cost_basis=Decimal("100.10"),
            entry_price=Decimal("50000.00"),
            entry_timestamp="2026-09-26T12:00:00+00:00",
        )

        # 1. Sinal SELL com Kill Switch ativo
        dec_sell = self.risk_engine.evaluate(
            account=account,
            position=open_pos,
            signal=Signal.SELL,
            signal_reason="Venda de sinal",
            current_price=Decimal("50000.00"),
            candle_timestamp=1700000060000,
            timeframe_ms=60000,
            kill_switch_active=True,
            daily_realized_pnl=Decimal("0.00"),
            last_closed_trade_candle_ts=None,
        )
        self.assertTrue(dec_sell.allowed)
        self.assertEqual(dec_sell.action, "SELL")

        # 2. Stop loss com Kill Switch ativo
        dec_sl = self.risk_engine.evaluate(
            account=account,
            position=open_pos,
            signal=Signal.HOLD,
            signal_reason="Neutro",
            current_price=Decimal("48000.00"),  # 4% de queda
            candle_timestamp=1700000060000,
            timeframe_ms=60000,
            kill_switch_active=True,
            daily_realized_pnl=Decimal("0.00"),
            last_closed_trade_candle_ts=None,
        )
        self.assertTrue(dec_sl.allowed)
        self.assertEqual(dec_sl.code, RiskDecisionCode.DEFENSIVE_EXIT_STOP_LOSS)
        self.assertEqual(dec_sl.action, "SELL")

    def test_11_hold_does_not_alter_wallet(self) -> None:
        """11. Sinal HOLD não autoriza trade nem altera carteira."""
        account = PaperAccount(
            usdt_balance=Decimal("10000.00"),
            btc_balance=Decimal("0.0"),
            updated_at="2026-09-26T12:00:00+00:00",
        )
        empty_pos = PaperPosition(
            side="NONE",
            quantity=Decimal("0.0"),
            cost_basis=Decimal("0.0"),
            entry_price=Decimal("0.0"),
            entry_timestamp="",
        )

        dec = self.risk_engine.evaluate(
            account=account,
            position=empty_pos,
            signal=Signal.HOLD,
            signal_reason="Sem cruzamento",
            current_price=Decimal("50000.00"),
            candle_timestamp=1700000060000,
            timeframe_ms=60000,
            kill_switch_active=False,
            daily_realized_pnl=Decimal("0.00"),
            last_closed_trade_candle_ts=None,
        )
        self.assertTrue(dec.allowed)
        self.assertEqual(dec.code, RiskDecisionCode.HOLD)
        self.assertEqual(dec.action, "HOLD")

    def test_12_risk_engine_does_not_import_ccxt(self) -> None:
        """12. Garante que risk.py não importa CCXT nem realiza conexões de rede."""
        source = inspect.getsource(risk_module)
        self.assertNotIn("ccxt", source)
        self.assertNotIn("requests", source)
        self.assertNotIn("urllib", source)
        self.assertNotIn("http.client", source)
        self.assertNotIn("socket", source)

    def test_13_status_works_offline(self) -> None:
        """13. O comando de status funciona em modo offline completo com métricas de risco."""
        report = format_paper_status_report(self.storage, self.config)
        self.assertIn("Risk:", report)
        self.assertIn("Kill switch: INACTIVE", report)
        self.assertIn("Daily realized P/L:", report)
        self.assertIn("Max daily loss: 50.00 USDT", report)
        self.assertIn("Stop loss: 2.0%", report)
        self.assertIn("Cooldown:", report)
        self.assertIn("Trading mode: PAPER (SIMULATION ONLY)", report)
        self.assertIn("Real trading: DISABLED", report)

    def test_14_kill_switch_persistence_across_restart(self) -> None:
        """14. Estado do Kill Switch sobrevive à reinicialização da aplicação."""
        self.storage.set_kill_switch(True)

        # Nova instância simulando reinício de processo
        storage2 = PaperStorage(db_path=self.db_path)
        self.assertTrue(storage2.get_kill_switch())

        # Desativa e valida nova instância
        storage2.set_kill_switch(False)
        storage3 = PaperStorage(db_path=self.db_path)
        self.assertFalse(storage3.get_kill_switch())

    def test_15_reset_clears_risk_state(self) -> None:
        """15. Reset do paper limpa estado do kill switch, último bloqueio e histórico."""
        self.storage.set_kill_switch(True)
        self.storage.set_last_risk_block("TEST_BLOCK", "Motivo de teste")

        self.storage.reset_db(initial_cash=Decimal("10000.00"))

        self.assertFalse(self.storage.get_kill_switch())
        self.assertIsNone(self.storage.get_last_risk_block())
        self.assertEqual(self.storage.get_trades_count(), 0)
        self.assertEqual(self.storage.get_account().usdt_balance, Decimal("10000.00"))

    def test_16_migration_preserves_fase5_database(self) -> None:
        """16. Banco de dados da FASE 5 (sem exit_reason) migra de forma idempotente sem perda."""
        fase5_db_path = Path(self.tmp_dir.name) / "fase5_legacy.sqlite3"
        conn = sqlite3.connect(str(fase5_db_path))
        # Cria schema original da FASE 5 sem exit_reason
        conn.execute("""
            CREATE TABLE paper_account (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                usdt_balance TEXT NOT NULL,
                btc_balance TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)
        conn.execute("""
            CREATE TABLE paper_position (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                side TEXT NOT NULL,
                quantity TEXT NOT NULL,
                cost_basis TEXT NOT NULL,
                entry_price TEXT NOT NULL,
                entry_timestamp TEXT NOT NULL
            );
        """)
        conn.execute("""
            CREATE TABLE paper_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                candle_timestamp INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                price TEXT NOT NULL,
                quantity TEXT NOT NULL,
                notional TEXT NOT NULL,
                fee TEXT NOT NULL,
                realized_pnl TEXT
            );
        """)
        conn.execute("""
            CREATE TABLE paper_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        conn.execute(
            "INSERT INTO paper_account VALUES (1, '9500.00', '0.01000000', '2026-09-25T10:00:00+00:00');"
        )
        conn.execute(
            "INSERT INTO paper_trades (timestamp, candle_timestamp, symbol, side, price, quantity, notional, fee, realized_pnl) "
            "VALUES ('2026-09-25T10:00:00+00:00', 1699999990000, 'BTC/USDT', 'BUY', '50000.0', '0.01', '500.0', '0.5', NULL);"
        )
        conn.commit()
        conn.close()

        # Abre com o PaperStorage da FASE 6 e executa init_db
        legacy_storage = PaperStorage(db_path=fase5_db_path)
        legacy_storage.init_db()

        # Verifica integridade dos dados existentes
        account = legacy_storage.get_account()
        self.assertEqual(account.usdt_balance, Decimal("9500.00"))
        self.assertEqual(account.btc_balance, Decimal("0.01000000"))

        trades = legacy_storage.get_trades()
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].side, "BUY")
        self.assertIsNone(trades[0].exit_reason)

        # Insere novo trade da FASE 6 com exit_reason
        new_account = PaperAccount(
            usdt_balance=Decimal("10000.00"),
            btc_balance=Decimal("0.0"),
            updated_at="2026-09-26T12:00:00+00:00",
        )
        new_pos = PaperPosition(
            side="NONE",
            quantity=Decimal("0.0"),
            cost_basis=Decimal("0.0"),
            entry_price=Decimal("0.0"),
            entry_timestamp="",
        )
        new_trade = PaperTrade(
            id=None,
            timestamp="2026-09-26T12:00:00+00:00",
            candle_timestamp=1700000000000,
            symbol="BTC/USDT",
            side="SELL",
            price=Decimal("51000.00"),
            quantity=Decimal("0.01"),
            notional=Decimal("510.00"),
            fee=Decimal("0.51"),
            realized_pnl=Decimal("9.49"),
            exit_reason="STOP_LOSS",
        )
        legacy_storage.execute_trade_transaction(
            new_account=new_account,
            new_position=new_pos,
            trade=new_trade,
            candle_timestamp=1700000000000,
        )

        all_trades = legacy_storage.get_trades()
        self.assertEqual(len(all_trades), 2)
        self.assertEqual(all_trades[0].exit_reason, "STOP_LOSS")
        self.assertIsNone(all_trades[1].exit_reason)

    def test_17_transaction_atomicity_on_error(self) -> None:
        """17. Falha durante a transação SQLite dispara rollback sem estado inconsistente."""
        initial_account = self.storage.get_account()
        initial_trades_count = self.storage.get_trades_count()

        bad_trade = PaperTrade(
            id=None,
            timestamp="2026-09-26T12:00:00+00:00",
            candle_timestamp=1700000000000,
            symbol="BTC/USDT",
            side="BUY",
            price=Decimal("50000.00"),
            quantity=Decimal("0.002"),
            notional=Decimal("100.00"),
            fee=Decimal("0.10"),
            realized_pnl=None,
            exit_reason=None,
        )
        new_account = PaperAccount(
            usdt_balance=Decimal("9899.90"),
            btc_balance=Decimal("0.002"),
            updated_at="2026-09-26T12:00:00+00:00",
        )
        # Posição inválida para forçar falha no SQLite ou mock de erro
        with patch.object(self.storage, "connection") as mock_conn:
            # Simula erro de conexão/SQL
            mock_conn.side_effect = sqlite3.OperationalError("Simulated SQLite failure")
            with self.assertRaises(sqlite3.OperationalError):
                self.storage.execute_trade_transaction(
                    new_account=new_account,
                    new_position=PaperPosition("LONG", Decimal("0.002"), Decimal("100.10"), Decimal("50000.0"), ""),
                    trade=bad_trade,
                    candle_timestamp=1700000000000,
                )

        # Verifica que o estado real do banco permanece inalterado
        self.assertEqual(self.storage.get_account().usdt_balance, initial_account.usdt_balance)
        self.assertEqual(self.storage.get_trades_count(), initial_trades_count)


if __name__ == "__main__":
    unittest.main()
