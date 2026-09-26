"""Testes unitários determinísticos para o motor de estratégia (Strategy Engine)."""

import unittest
from finbot.exchange import CandleData
from finbot.strategy import Signal, evaluate_sma_crossover


class TestStrategyEngine(unittest.TestCase):
    """Testa a lógica determinística de cruzamento de médias móveis (SMA)."""

    def test_buy_crossover(self) -> None:
        """Verifica sinal BUY quando a média curta cruza acima da longa."""
        # 10 candles anteriores em queda, candle 11 com salto forte
        prices = [10.0, 10.0, 10.0, 10.0, 10.0, 9.0, 9.0, 9.0, 9.0, 9.0, 20.0]
        result = evaluate_sma_crossover(prices, short_window=5, long_window=10)

        self.assertEqual(result.signal, Signal.BUY)
        self.assertIn("BUY crossover", result.reason)
        self.assertIsNotNone(result.short_ma)
        self.assertIsNotNone(result.long_ma)
        self.assertIsNotNone(result.prev_short_ma)
        self.assertIsNotNone(result.prev_long_ma)
        # Confirma matematicamente a condição de cruzamento de alta
        self.assertLessEqual(result.prev_short_ma, result.prev_long_ma)  # type: ignore[operator]
        self.assertGreater(result.short_ma, result.long_ma)  # type: ignore[operator]

    def test_sell_crossover(self) -> None:
        """Verifica sinal SELL quando a média curta cruza abaixo da longa."""
        # 10 candles anteriores em alta, candle 11 com queda forte
        prices = [10.0, 10.0, 10.0, 10.0, 10.0, 11.0, 11.0, 11.0, 11.0, 11.0, 1.0]
        result = evaluate_sma_crossover(prices, short_window=5, long_window=10)

        self.assertEqual(result.signal, Signal.SELL)
        self.assertIn("SELL crossover", result.reason)
        self.assertIsNotNone(result.short_ma)
        self.assertIsNotNone(result.long_ma)
        self.assertIsNotNone(result.prev_short_ma)
        self.assertIsNotNone(result.prev_long_ma)
        # Confirma matematicamente a condição de cruzamento de baixa
        self.assertGreaterEqual(result.prev_short_ma, result.prev_long_ma)  # type: ignore[operator]
        self.assertLess(result.short_ma, result.long_ma)  # type: ignore[operator]

    def test_hold_no_crossover(self) -> None:
        """Verifica sinal HOLD quando não há evento de cruzamento."""
        # Preços constantes: médias idênticas, sem cruzamento
        prices = [100.0] * 15
        result = evaluate_sma_crossover(prices, short_window=5, long_window=10)

        self.assertEqual(result.signal, Signal.HOLD)
        self.assertEqual(result.reason, "no crossover detected")
        self.assertEqual(result.short_ma, 100.0)
        self.assertEqual(result.long_ma, 100.0)

    def test_hold_continuous_trend_no_crossover(self) -> None:
        """Verifica que short > long mantido por vários candles resulta em HOLD (sem repetição de sinal)."""
        # Média curta já estava acima no candle anterior e continua acima no candle atual
        prices = [50.0] * 5 + [100.0] * 10
        result = evaluate_sma_crossover(prices, short_window=5, long_window=10)

        self.assertEqual(result.signal, Signal.HOLD)
        self.assertEqual(result.reason, "no crossover detected")

    def test_insufficient_data(self) -> None:
        """Verifica retorno de HOLD quando não há candles suficientes para o cálculo."""
        # Necessário long_window + 1 = 11 candles; fornecemos apenas 6
        prices = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0]
        result = evaluate_sma_crossover(prices, short_window=5, long_window=10)

        self.assertEqual(result.signal, Signal.HOLD)
        self.assertIn("Dados insuficientes", result.reason)
        self.assertIsNone(result.short_ma)
        self.assertIsNone(result.long_ma)

    def test_invalid_window_configuration(self) -> None:
        """Verifica que parâmetros incorretos de janela lançam ValueError."""
        prices = [10.0] * 20

        # short_window <= 0
        with self.assertRaises(ValueError):
            evaluate_sma_crossover(prices, short_window=0, long_window=10)

        # long_window <= short_window
        with self.assertRaises(ValueError):
            evaluate_sma_crossover(prices, short_window=10, long_window=5)

        # long_window == short_window
        with self.assertRaises(ValueError):
            evaluate_sma_crossover(prices, short_window=5, long_window=5)

    def test_interoperability_with_candle_data_objects(self) -> None:
        """Verifica compatibilidade com instâncias de CandleData do módulo exchange."""
        candles = [
            CandleData(
                timestamp=1600000000000 + i * 60000,
                open=10.0,
                high=11.0,
                low=9.0,
                close=float(i + 1),
                volume=1.0,
            )
            for i in range(15)
        ]
        result = evaluate_sma_crossover(candles, short_window=5, long_window=10)
        self.assertIn(result.signal, [Signal.BUY, Signal.SELL, Signal.HOLD])
        self.assertIsNotNone(result.short_ma)
        self.assertIsNotNone(result.long_ma)


if __name__ == "__main__":
    unittest.main()
