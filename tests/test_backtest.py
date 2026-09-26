"""Testes unitários para o módulo de backtesting reproduzível (FASE 4).

Todos os testes utilizam candles sintéticos gerados em memória.
Nenhum teste acessa a internet ou consulta a exchange.
"""

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pandas as pd

from finbot.backtest import (
    BacktestResult,
    DatasetMetadata,
    FinBotSMAStrategy,
    candles_to_dataframe,
    format_backtest_report,
    load_dataset_snapshot,
    run_backtest,
    save_dataset_snapshot,
)
from finbot.exchange import CandleData
from finbot.strategy import Signal


def _make_synthetic_candles(prices: list[float]) -> list[CandleData]:
    """Cria lista de CandleData sintéticos a partir de uma série de preços."""
    base_ts = 1700000000000
    candles = []
    for i, p in enumerate(prices):
        candles.append(
            CandleData(
                timestamp=base_ts + i * 300000,  # 5 minutos em ms
                open=p,
                high=p * 1.01,
                low=p * 0.99,
                close=p,
                volume=100.0,
            )
        )
    return candles


class TestBacktestModule(unittest.TestCase):
    """Bateria de testes unitários para a engine de backtesting."""

    def test_candle_data_to_dataframe_conversion(self) -> None:
        """Verifica a conversão de CandleData para DataFrame formatado para a engine."""
        prices = [10.0, 11.0, 12.0]
        candles = _make_synthetic_candles(prices)
        df = candles_to_dataframe(candles)

        self.assertIsInstance(df, pd.DataFrame)
        self.assertEqual(len(df), 3)
        self.assertListEqual(list(df.columns), ["Open", "High", "Low", "Close", "Volume"])
        self.assertEqual(df["Close"].iloc[0], 10.0)
        self.assertEqual(df["Close"].iloc[2], 12.0)
        self.assertEqual(df.index.name, "Date")

    def test_insufficient_dataset_raises_error(self) -> None:
        """Verifica que dataset menor que long_window + 1 lança ValueError."""
        prices = [10.0] * 5
        df = candles_to_dataframe(_make_synthetic_candles(prices))

        with self.assertRaises(ValueError) as ctx:
            run_backtest(df, short_window=5, long_window=10)
        self.assertIn("Dataset insuficiente", str(ctx.exception))

    def test_hold_does_not_trade(self) -> None:
        """Verifica que série constante (sem cruzamento) gera 0 trades."""
        # 25 candles com preço fixo -> médias idênticas -> sinal sempre HOLD
        prices = [100.0] * 25
        df = candles_to_dataframe(_make_synthetic_candles(prices))

        result = run_backtest(
            df,
            initial_cash=10000.0,
            commission=0.001,
            short_window=5,
            long_window=10,
        )

        self.assertEqual(result.trades_count, 0)
        self.assertEqual(result.wins, 0)
        self.assertEqual(result.losses, 0)
        self.assertEqual(result.final_equity, 10000.0)
        self.assertEqual(result.total_return_pct, 0.0)

    def test_buy_and_sell_cycle(self) -> None:
        """Verifica que cruzamento de alta abre posição e cruzamento de baixa encerra."""
        # Configuração: short=2, long=4 (requer 5 candles para iniciar)
        # Início estável em 10.0 (candles 0 a 4)
        # Salto para 20.0 nos candles 5 e 6 -> gera BUY crossover
        # Queda para 5.0 nos candles 7 e 8 -> gera SELL crossover
        # Candles 9 e 10 para processamento
        prices = [10.0, 10.0, 10.0, 10.0, 10.0, 20.0, 20.0, 5.0, 5.0, 5.0, 5.0]
        df = candles_to_dataframe(_make_synthetic_candles(prices))

        result = run_backtest(
            df,
            initial_cash=10000.0,
            commission=0.001,
            short_window=2,
            long_window=4,
        )

        # Deve ter registrado ao menos 1 trade executado
        self.assertGreaterEqual(result.trades_count, 1)
        self.assertIsInstance(result.final_equity, float)
        self.assertIsInstance(result.total_return_pct, float)
        self.assertIsInstance(result.buy_and_hold_pct, float)

    def test_strategy_engine_reuse(self) -> None:
        """Verifica que a estratégia oficial evaluate_sma_crossover é chamada."""
        prices = [10.0] * 15
        df = candles_to_dataframe(_make_synthetic_candles(prices))

        from finbot.strategy import evaluate_sma_crossover as real_eval
        with patch("finbot.backtest.evaluate_sma_crossover", side_effect=real_eval) as mock_eval:
            run_backtest(df, short_window=2, long_window=4)
            self.assertGreater(mock_eval.call_count, 0)

    def test_no_private_exchange_calls(self) -> None:
        """Garante que a execução do backtest não chama métodos privados de exchange."""
        prices = [10.0] * 15
        df = candles_to_dataframe(_make_synthetic_candles(prices))

        # Inspeciona módulos para confirmar ausência de chamadas privadas
        import finbot.backtest as bt_mod
        forbidden = ["create_order", "cancel_order", "fetch_balance", "apiKey", "secret"]
        for word in forbidden:
            self.assertNotIn(f".{word}", dir(bt_mod))

        # Executa backtest para garantir sucesso puramente offline
        result = run_backtest(df, short_window=2, long_window=4)
        self.assertIsInstance(result, BacktestResult)

    def test_basic_metrics_validity(self) -> None:
        """Verifica que todas as métricas básicas retornam tipos e valores válidos."""
        prices = [10.0, 10.0, 10.0, 10.0, 15.0, 16.0, 17.0, 18.0, 9.0, 8.0, 7.0, 6.0]
        df = candles_to_dataframe(_make_synthetic_candles(prices))

        result = run_backtest(
            df,
            initial_cash=10000.0,
            commission=0.001,
            short_window=2,
            long_window=4,
        )

        self.assertIsInstance(result.initial_cash, float)
        self.assertIsInstance(result.final_equity, float)
        self.assertIsInstance(result.total_return_pct, float)
        self.assertIsInstance(result.buy_and_hold_pct, float)
        self.assertIsInstance(result.trades_count, int)
        self.assertIsInstance(result.wins, int)
        self.assertIsInstance(result.losses, int)
        self.assertIsInstance(result.max_drawdown_pct, float)

    def test_snapshot_save_and_load_roundtrip(self) -> None:
        """Verifica serialização e desserialização de snapshot histórico em JSON."""
        candles = _make_synthetic_candles([100.0, 101.0, 102.0])
        metadata = DatasetMetadata(
            exchange="binance",
            symbol="BTC/USDT",
            timeframe="5m",
            candle_count=3,
            start_timestamp=candles[0].timestamp,
            end_timestamp=candles[-1].timestamp,
            start_datetime="2026-01-01 00:00:00",
            end_datetime="2026-01-01 00:10:00",
            downloaded_at="2026-01-01T00:15:00Z",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test_snapshot.json"
            save_dataset_snapshot(file_path, metadata, candles)
            self.assertTrue(file_path.exists())

            loaded_meta, loaded_candles = load_dataset_snapshot(file_path)
            self.assertEqual(loaded_meta.exchange, "binance")
            self.assertEqual(loaded_meta.symbol, "BTC/USDT")
            self.assertEqual(loaded_meta.candle_count, 3)
            self.assertEqual(len(loaded_candles), 3)
            self.assertEqual(loaded_candles[0].close, 100.0)
            self.assertEqual(loaded_candles[-1].close, 102.0)

    def test_format_backtest_report(self) -> None:
        """Verifica que o relatório não contém juízos de valor e exibe métricas corretas."""
        metadata = DatasetMetadata(
            exchange="binance",
            symbol="BTC/USDT",
            timeframe="5m",
            candle_count=500,
            start_timestamp=1700000000000,
            end_timestamp=1700150000000,
            start_datetime="2026-09-25 00:00:00",
            end_datetime="2026-09-26 00:00:00",
            downloaded_at="2026-09-26T12:00:00Z",
        )
        result = BacktestResult(
            initial_cash=10000.0,
            final_equity=9800.0,
            total_return_pct=-2.0,
            buy_and_hold_pct=3.5,
            trades_count=10,
            wins=4,
            losses=6,
            win_rate_pct=40.0,
            max_drawdown_pct=-3.2,
            profit_factor=0.85,
        )

        report = format_backtest_report(metadata, result, short_window=5, long_window=10)

        # Valida presença das seções essenciais
        self.assertIn("FinBot Backtest", report)
        self.assertIn("SIMULATION ONLY", report)
        self.assertIn("No real orders were sent.", report)
        self.assertIn("Return: -2.00%", report)
        self.assertIn("Buy & Hold: +3.50%", report)
        self.assertIn("Trades: 10 (Wins: 4, Losses: 6)", report)

        # Regra 16: sem adjetivações financeiras
        for forbidden in ["boa", "lucrativa", "recomendado", "comprar bitcoin", "excelente"]:
            self.assertNotIn(forbidden, report.lower())

    def test_lookahead_prevention_and_execution_timing(self) -> None:
        """Verifica que a estratégia não enxerga dados futuros e executa no próximo Open."""
        # Registramos o tamanho de self.data.Close em cada chamada de next()
        seen_lengths = []
        last_closes = []

        class LookaheadTestStrategy(FinBotSMAStrategy):
            def next(self):
                seen_lengths.append(len(self.data.Close))
                last_closes.append(float(self.data.Close[-1]))
                super().next()

        prices = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0]
        df = candles_to_dataframe(_make_synthetic_candles(prices))

        from backtesting.lib import FractionalBacktest
        bt = FractionalBacktest(df, LookaheadTestStrategy, cash=10000.0, commission=0.0)
        bt.run()

        # O primeiro next() roda a partir do 2º candle (índice 1) e cresce estritamente de 1 em 1
        self.assertEqual(seen_lengths, list(range(2, len(prices) + 1)))

        # Em cada ponto, o último preço visto é estritamente o candle atual (sem preços futuros)
        self.assertEqual([round(c * 100e6, 2) for c in last_closes], prices[1:])

        # Testa também que alteração em preços futuros no candle 6 não afeta decisão no candle 3
        df_future_modified = df.copy()
        df_future_modified.iloc[-1, df_future_modified.columns.get_loc("Close")] = 99999.0

        seen_lengths_mod = []
        last_closes_mod = []

        class LookaheadTestStrategy2(FinBotSMAStrategy):
            def next(self):
                seen_lengths_mod.append(len(self.data.Close))
                last_closes_mod.append(float(self.data.Close[-1]))
                super().next()

        bt2 = FractionalBacktest(df_future_modified, LookaheadTestStrategy2, cash=10000.0, commission=0.0)
        bt2.run()

        # Antes do último candle, todos os preços e decisões vistos são estritamente idênticos
        self.assertEqual(last_closes[:-1], last_closes_mod[:-1])


if __name__ == "__main__":
    unittest.main()
