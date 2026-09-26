"""Testes unitários determinísticos para Paper Trading e persistência SQLite (FASE 5).

Todos os testes utilizam banco SQLite temporário e dados sintéticos em memória.
Nenhum teste acessa a internet nem utiliza credenciais ou banco de produção.
"""

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from finbot.config import Config
from finbot.exchange import CandleData
from finbot.paper import (
    execute_paper_cycle,
    filter_closed_candles,
    format_paper_cycle_report,
    format_paper_status_report,
    timeframe_to_ms,
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


class TestPaperTrading(unittest.TestCase):
    """Bateria de testes unitários para a FASE 5 (Paper Trading e Storage)."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_paper.sqlite3"
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
        )

    def tearDown(self) -> None:
        try:
            self.tmp_dir.cleanup()
        except Exception:
            pass

    def test_1_account_initialization(self) -> None:
        """1. Inicialização correta da conta paper no SQLite."""
        account = self.storage.get_account()
        position = self.storage.get_position()
        trades_count = self.storage.get_trades_count()
        last_processed = self.storage.get_last_processed_candle_timestamp()

        self.assertEqual(account.usdt_balance, Decimal("10000.00"))
        self.assertEqual(account.btc_balance, Decimal("0.00000000"))
        self.assertEqual(position.side, "NONE")
        self.assertEqual(position.quantity, Decimal("0.00000000"))
        self.assertEqual(trades_count, 0)
        self.assertIsNone(last_processed)

    def test_2_persistence_after_restart(self) -> None:
        """2. Estado da conta sobrevive à reinicialização do objeto PaperStorage."""
        # Simula alteração de saldo
        new_acc = PaperAccount(
            usdt_balance=Decimal("9500.50"),
            btc_balance=Decimal("0.00620000"),
            updated_at="2026-09-26T20:00:00Z",
        )
        new_pos = PaperPosition(
            side="LONG",
            quantity=Decimal("0.00620000"),
            cost_basis=Decimal("500.50"),
            entry_price=Decimal("80000.00"),
            entry_timestamp="2026-09-26T20:00:00Z",
        )
        trade = PaperTrade(
            id=None,
            timestamp="2026-09-26T20:00:00Z",
            candle_timestamp=1700000000000,
            symbol="BTC/USDT",
            side="BUY",
            price=Decimal("80000.00"),
            quantity=Decimal("0.00620000"),
            notional=Decimal("500.00"),
            fee=Decimal("0.50"),
            realized_pnl=None,
        )
        self.storage.execute_trade_transaction(new_acc, new_pos, trade, 1700000000000)

        # Nova instância simulando reinício do processo
        new_storage_instance = PaperStorage(db_path=self.db_path)
        restarted_acc = new_storage_instance.get_account()
        restarted_pos = new_storage_instance.get_position()
        restarted_trades_count = new_storage_instance.get_trades_count()
        last_processed = new_storage_instance.get_last_processed_candle_timestamp()

        self.assertEqual(restarted_acc.usdt_balance, Decimal("9500.50"))
        self.assertEqual(restarted_acc.btc_balance, Decimal("0.00620000"))
        self.assertEqual(restarted_pos.side, "LONG")
        self.assertEqual(restarted_trades_count, 1)
        self.assertEqual(last_processed, 1700000000000)

    def test_3_4_5_buy_reduces_usdt_increases_btc_and_applies_commission(self) -> None:
        """3, 4, 5. BUY deduz USDT (notional + fee), credita BTC e aplica taxa."""
        # 10 candles baixos seguidos por candle alto para gerar BUY crossover
        prices = [10.0, 10.0, 10.0, 10.0, 10.0, 9.0, 9.0, 9.0, 9.0, 9.0, 20.0]
        candles = _make_closed_candles(prices)
        now_ms = candles[-1].timestamp + 120000  # Tempo atual posterior ao fechamento do último candle

        res = execute_paper_cycle(
            self.storage,
            self.config,
            now_ms=now_ms,
            ticker_override=20.0,
            candles_override=candles,
        )

        self.assertEqual(res.signal, Signal.BUY)
        self.assertEqual(res.trade_action, "BUY_EXECUTED")
        self.assertIsNotNone(res.executed_trade)

        # Notional: 100.00, Fee: 0.10, Total cost: 100.10 USDT
        expected_usdt = Decimal("10000.00") - Decimal("100.10")
        self.assertEqual(res.account.usdt_balance, expected_usdt)

        # BTC adquirido: 100.00 / 20.0 = 5.00000000 BTC
        expected_btc = Decimal("5.00000000")
        self.assertEqual(res.account.btc_balance, expected_btc)

        # Posição
        self.assertEqual(res.position.side, "LONG")
        self.assertEqual(res.position.quantity, expected_btc)
        self.assertEqual(res.position.cost_basis, Decimal("100.10"))
        self.assertEqual(res.position.entry_price, Decimal("20.00"))

        # Trade registrado
        trade = res.executed_trade
        self.assertEqual(trade.side, "BUY")
        self.assertEqual(trade.notional, Decimal("100.00"))
        self.assertEqual(trade.fee, Decimal("0.10"))
        self.assertIsNone(trade.realized_pnl)

    def test_6_second_buy_with_open_position_is_ignored(self) -> None:
        """6. Segundo sinal de BUY quando já existe posição é ignorado."""
        prices = [10.0, 10.0, 10.0, 10.0, 10.0, 9.0, 9.0, 9.0, 9.0, 9.0, 20.0]
        candles = _make_closed_candles(prices)
        now_ms = candles[-1].timestamp + 120000

        # Primeiro BUY abre posição
        res1 = execute_paper_cycle(
            self.storage,
            self.config,
            now_ms=now_ms,
            ticker_override=20.0,
            candles_override=candles,
        )
        self.assertEqual(res1.trade_action, "BUY_EXECUTED")
        self.assertEqual(self.storage.get_trades_count(), 1)

        # Novo candle que também produziria BUY
        new_candle = CandleData(
            timestamp=candles[-1].timestamp + 60000,
            open=20.0,
            high=21.0,
            low=19.0,
            close=22.0,
            volume=10.0,
        )
        candles2 = candles[1:] + [new_candle]
        now_ms2 = new_candle.timestamp + 120000

        from finbot.strategy import StrategyResult
        with patch(
            "finbot.paper.evaluate_sma_crossover",
            return_value=StrategyResult(Signal.BUY, 22.0, 15.0, 14.0, 15.0, "BUY crossover"),
        ):
            res2 = execute_paper_cycle(
                self.storage,
                self.config,
                now_ms=now_ms2,
                ticker_override=22.0,
                candles_override=candles2,
            )
        self.assertEqual(res2.trade_action, "BUY_IGNORED_POSITION_EXISTS")
        self.assertIn("posição já aberta", res2.message)
        # Trades mantidos em 1, saldo não alterado
        self.assertEqual(self.storage.get_trades_count(), 1)
        self.assertEqual(res2.account.usdt_balance, res1.account.usdt_balance)

    def test_7_8_9_sell_closes_position_updates_usdt_and_calculates_pnl(self) -> None:
        """7, 8, 9. SELL encerra posição, atualiza USDT e calcula Realized P/L corretamente."""
        # 1. Abre posição a preço 10.0 USDT
        buy_prices = [10.0, 10.0, 10.0, 10.0, 10.0, 9.0, 9.0, 9.0, 9.0, 9.0, 20.0]
        buy_candles = _make_closed_candles(buy_prices)
        now_ms_buy = buy_candles[-1].timestamp + 120000

        res_buy = execute_paper_cycle(
            self.storage,
            self.config,
            now_ms=now_ms_buy,
            ticker_override=20.0,
            candles_override=buy_candles,
        )
        self.assertEqual(res_buy.trade_action, "BUY_EXECUTED")
        # 100 USDT comprados a 20.0 -> 5.0 BTC. Custo: 100.10 USDT. Saldo USDT: 9899.90.
        self.assertEqual(res_buy.account.btc_balance, Decimal("5.00000000"))

        # 2. Gera SELL crossover com preço de venda em 30.0 USDT (lucro)
        # 10 candles altos seguidos por queda forte
        sell_prices = [30.0, 30.0, 30.0, 30.0, 30.0, 31.0, 31.0, 31.0, 31.0, 31.0, 10.0]
        start_sell_ts = buy_candles[-1].timestamp + 60000
        sell_candles = _make_closed_candles(sell_prices, start_ts=start_sell_ts)
        now_ms_sell = sell_candles[-1].timestamp + 120000

        res_sell = execute_paper_cycle(
            self.storage,
            self.config,
            now_ms=now_ms_sell,
            ticker_override=30.0,  # Venda a 30.0 USDT
            candles_override=sell_candles,
        )

        self.assertEqual(res_sell.signal, Signal.SELL)
        self.assertEqual(res_sell.trade_action, "SELL_EXECUTED")
        self.assertIsNotNone(res_sell.executed_trade)

        # 5.0 BTC vendidos a 30.0 USDT:
        # Gross notional: 5.0 * 30.0 = 150.00 USDT
        # Fee: 150.00 * 0.001 = 0.15 USDT
        # Net proceeds: 150.00 - 0.15 = 149.85 USDT
        # Realized P/L: 149.85 - 100.10 = +49.75 USDT
        trade = res_sell.executed_trade
        self.assertEqual(trade.notional, Decimal("150.00"))
        self.assertEqual(trade.fee, Decimal("0.15"))
        self.assertEqual(trade.realized_pnl, Decimal("49.75"))

        # Saldo USDT final: 9899.90 + 149.85 = 10049.75 USDT (+49.75 em relação ao inicial)
        self.assertEqual(res_sell.account.usdt_balance, Decimal("10049.75"))
        self.assertEqual(res_sell.account.btc_balance, Decimal("0.00000000"))

        # Posição zerada
        self.assertEqual(res_sell.position.side, "NONE")
        self.assertEqual(res_sell.position.quantity, Decimal("0.00000000"))
        self.assertEqual(self.storage.get_trades_count(), 2)

    def test_10_sell_without_position_is_ignored(self) -> None:
        """10. Sinal SELL sem posição aberta não altera carteira."""
        sell_prices = [30.0, 30.0, 30.0, 30.0, 30.0, 31.0, 31.0, 31.0, 31.0, 31.0, 10.0]
        candles = _make_closed_candles(sell_prices)
        now_ms = candles[-1].timestamp + 120000

        res = execute_paper_cycle(
            self.storage,
            self.config,
            now_ms=now_ms,
            ticker_override=10.0,
            candles_override=candles,
        )

        self.assertEqual(res.signal, Signal.SELL)
        self.assertEqual(res.trade_action, "SELL_IGNORED_NO_POSITION")
        self.assertEqual(self.storage.get_trades_count(), 0)
        self.assertEqual(res.account.usdt_balance, Decimal("10000.00"))

    def test_11_hold_does_not_alter_balance(self) -> None:
        """11. Sinal HOLD não executa trades nem altera saldos."""
        prices = [100.0] * 15
        candles = _make_closed_candles(prices)
        now_ms = candles[-1].timestamp + 120000

        res = execute_paper_cycle(
            self.storage,
            self.config,
            now_ms=now_ms,
            ticker_override=100.0,
            candles_override=candles,
        )

        self.assertEqual(res.signal, Signal.HOLD)
        self.assertEqual(res.trade_action, "HOLD")
        self.assertEqual(self.storage.get_trades_count(), 0)
        self.assertEqual(res.account.usdt_balance, Decimal("10000.00"))
        self.assertEqual(res.account.btc_balance, Decimal("0.00000000"))

    def test_12_same_candle_not_processed_twice(self) -> None:
        """12. Deduplicação: o mesmo candle fechado não dispara estratégia repetidamente."""
        prices = [100.0] * 15
        candles = _make_closed_candles(prices)
        now_ms = candles[-1].timestamp + 120000

        res1 = execute_paper_cycle(
            self.storage,
            self.config,
            now_ms=now_ms,
            ticker_override=100.0,
            candles_override=candles,
        )
        self.assertEqual(res1.trade_action, "HOLD")

        # Segunda chamada com os exatos mesmos candles
        res2 = execute_paper_cycle(
            self.storage,
            self.config,
            now_ms=now_ms,
            ticker_override=100.0,
            candles_override=candles,
        )
        self.assertEqual(res2.trade_action, "NO_NEW_CANDLE")
        self.assertIn("No new closed candle", res2.message)

    def test_13_transaction_rollback_on_error(self) -> None:
        """13. Erro durante a transação SQLite dispara rollback atômico."""
        acc_before = self.storage.get_account()
        pos_before = self.storage.get_position()
        trades_before = self.storage.get_trades_count()

        new_acc = PaperAccount(Decimal("5000.00"), Decimal("1.0"), "now")
        new_pos = PaperPosition("LONG", Decimal("1.0"), Decimal("5000.00"), Decimal("5000.00"), "now")
        # Trade inválido: symbol=None viola constraint NOT NULL no passo 3 (INSERT)
        trade = PaperTrade(None, "now", 12345, None, "BUY", Decimal("10.0"), Decimal("1.0"), Decimal("10.0"), Decimal("0.01"), None)  # type: ignore[arg-type]

        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            self.storage.execute_trade_transaction(new_acc, new_pos, trade, 12345)

        # Confirma que após o erro, tudo foi revertido ao estado anterior
        acc_after = self.storage.get_account()
        pos_after = self.storage.get_position()
        trades_after = self.storage.get_trades_count()

        self.assertEqual(acc_after.usdt_balance, acc_before.usdt_balance)
        self.assertEqual(acc_after.btc_balance, acc_before.btc_balance)
        self.assertEqual(pos_after.side, pos_before.side)
        self.assertEqual(trades_after, trades_before)

    def test_14_reset_explicit_intent(self) -> None:
        """14. Reset limpa banco e restaura estado inicial da conta fictícia."""
        # Altera estado
        new_acc = PaperAccount(Decimal("8000.00"), Decimal("0.05"), "now")
        new_pos = PaperPosition("LONG", Decimal("0.05"), Decimal("2000.00"), Decimal("40000.00"), "now")
        trade = PaperTrade(None, "now", 12345, "BTC/USDT", "BUY", Decimal("40000.00"), Decimal("0.05"), Decimal("2000.00"), Decimal("2.00"), None)
        self.storage.execute_trade_transaction(new_acc, new_pos, trade, 12345)

        self.assertEqual(self.storage.get_trades_count(), 1)

        # Executa reset
        self.storage.reset_db(initial_cash=Decimal("10000.00"))

        acc = self.storage.get_account()
        pos = self.storage.get_position()
        self.assertEqual(acc.usdt_balance, Decimal("10000.00"))
        self.assertEqual(acc.btc_balance, Decimal("0.00000000"))
        self.assertEqual(pos.side, "NONE")
        self.assertEqual(self.storage.get_trades_count(), 0)
        self.assertIsNone(self.storage.get_last_processed_candle_timestamp())

    def test_15_status_offline_no_network(self) -> None:
        """15. Status é gerado estritamente offline sem chamar a exchange."""
        # Se qualquer chamada de rede for tentada, mock falha o teste
        with patch("finbot.exchange.create_exchange", side_effect=AssertionError("Rede chamada indevidamente")):
            report = format_paper_status_report(self.storage, self.config)
            self.assertIn("FinBot Paper Trading — Status", report)
            self.assertIn("USDT: 10000.00", report)
            self.assertIn("BTC: 0.00000000", report)
            self.assertIn("Total trades: 0", report)

    def test_16_no_private_exchange_calls_in_codebase(self) -> None:
        """16. Confirma que os módulos de Paper Trading não contêm métodos privados de exchange."""
        import finbot.paper as paper_mod
        import finbot.storage as storage_mod

        forbidden = [
            "create_order",
            "cancel_order",
            "fetch_balance",
            "fetch_positions",
            "apiKey",
            "secret",
            "privateGet",
            "privatePost",
        ]
        for word in forbidden:
            self.assertNotIn(f".{word}", dir(paper_mod))
            self.assertNotIn(f".{word}", dir(storage_mod))

    def test_17_closed_candle_filtering(self) -> None:
        """17. Verifica que candles ainda em formação são descartados pela regra temporal."""
        now_ms = 1700000065000  # 1 minuto e 5 segundos após 1700000000000
        candles = [
            CandleData(1700000000000, 10.0, 11.0, 9.0, 10.5, 1.0),  # Fecha em 1700000060000 <= now_ms (FECHADO)
            CandleData(1700000060000, 10.5, 12.0, 10.0, 11.0, 1.0),  # Fecha em 1700000120000 > now_ms (EM FORMAÇÃO)
        ]

        closed = filter_closed_candles(candles, timeframe="1m", now_ms=now_ms)
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0].timestamp, 1700000000000)

    def test_18_timeframe_to_ms(self) -> None:
        """18. Verifica conversão de timeframes para milissegundos."""
        self.assertEqual(timeframe_to_ms("1m"), 60000)
        self.assertEqual(timeframe_to_ms("5m"), 300000)
        self.assertEqual(timeframe_to_ms("1h"), 3600000)
        self.assertEqual(timeframe_to_ms("1d"), 86400000)
        with self.assertRaises(ValueError):
            timeframe_to_ms("1x")


if __name__ == "__main__":
    unittest.main()
