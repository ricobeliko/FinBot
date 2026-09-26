"""Testes unitários locais para estruturas do módulo exchange."""

import unittest
from finbot.exchange import CandleData, ExchangeError, TickerData, create_exchange


class TestExchangeStructures(unittest.TestCase):
    """Testa estruturas de dados e validações locais de exchange."""

    def test_ticker_data_fields(self) -> None:
        """Verifica a integridade dos campos do TickerData."""
        ticker = TickerData(
            symbol="BTC/USDT",
            last=50000.0,
            bid=49999.0,
            ask=50001.0,
            timestamp=1600000000000,
            datetime="2020-09-13T12:26:40.000Z",
        )
        self.assertEqual(ticker.symbol, "BTC/USDT")
        self.assertEqual(ticker.last, 50000.0)
        self.assertEqual(ticker.bid, 49999.0)
        self.assertEqual(ticker.ask, 50001.0)

    def test_candle_data_formatted_time(self) -> None:
        """Verifica o método formatador de data/hora do CandleData."""
        candle = CandleData(
            timestamp=1600000000000,
            open=50000.0,
            high=50100.0,
            low=49900.0,
            close=50050.0,
            volume=10.5,
        )
        self.assertEqual(candle.open, 50000.0)
        self.assertEqual(candle.formatted_time, "2020-09-13 12:26:40")

    def test_unsupported_exchange_raises_error(self) -> None:
        """Verifica se exchange inexistente lança ExchangeError."""
        with self.assertRaises(ExchangeError):
            create_exchange("exchange_inexistente_xyz_123")


if __name__ == "__main__":
    unittest.main()
