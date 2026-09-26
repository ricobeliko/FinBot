"""Módulo de acesso a dados públicos de mercado via CCXT."""

from dataclasses import dataclass
from datetime import datetime, timezone
import ccxt


class ExchangeError(Exception):
    """Exceção para erros operacionais esperados ao consultar a exchange."""


@dataclass(frozen=True)
class TickerData:
    """Dados resumidos de ticker público de mercado."""

    symbol: str
    last: float | None
    bid: float | None
    ask: float | None
    timestamp: int | None
    datetime: str | None


@dataclass(frozen=True)
class CandleData:
    """Dados de um candle público (OHLCV)."""

    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def formatted_time(self) -> str:
        """Retorna o timestamp formatado em data/hora UTC."""
        dt = datetime.fromtimestamp(self.timestamp / 1000, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S")


def create_exchange(exchange_id: str = "binance") -> ccxt.Exchange:
    """Inicializa a exchange no CCXT com rate limit ativado.

    Apenas dados públicos são consultados. Nenhuma API key ou secret é utilizada.
    """
    exchange_class = getattr(ccxt, exchange_id.lower(), None)
    if exchange_class is None:
        raise ExchangeError(f"Exchange '{exchange_id}' não é suportada pelo CCXT.")

    try:
        return exchange_class({"enableRateLimit": True})
    except Exception as exc:
        raise ExchangeError(f"Falha ao instanciar exchange '{exchange_id}': {exc}") from exc


def fetch_ticker(exchange: ccxt.Exchange, symbol: str) -> TickerData:
    """Consulta dados de ticker público para um símbolo."""
    try:
        raw_ticker = exchange.fetch_ticker(symbol)
        return TickerData(
            symbol=raw_ticker.get("symbol", symbol),
            last=raw_ticker.get("last"),
            bid=raw_ticker.get("bid"),
            ask=raw_ticker.get("ask"),
            timestamp=raw_ticker.get("timestamp"),
            datetime=raw_ticker.get("datetime"),
        )
    except ccxt.BadSymbol as exc:
        raise ExchangeError(f"Símbolo '{symbol}' inválido ou indisponível na exchange '{exchange.id}': {exc}") from exc
    except (ccxt.NetworkError, ccxt.RequestTimeout, ccxt.ExchangeNotAvailable) as exc:
        raise ExchangeError(f"Erro de conexão/rede ao consultar ticker na exchange '{exchange.id}': {exc}") from exc
    except ccxt.ExchangeError as exc:
        raise ExchangeError(f"Erro da exchange '{exchange.id}' ao consultar ticker: {exc}") from exc
    except ccxt.BaseError as exc:
        raise ExchangeError(f"Erro geral no CCXT ao consultar ticker: {exc}") from exc


def fetch_candles(
    exchange: ccxt.Exchange,
    symbol: str,
    timeframe: str = "1m",
    limit: int = 5,
) -> list[CandleData]:
    """Consulta conjunto recente de candles públicos (OHLCV)."""
    try:
        raw_candles = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        candles: list[CandleData] = []
        for c in raw_candles:
            if len(c) >= 6:
                candles.append(
                    CandleData(
                        timestamp=int(c[0]),
                        open=float(c[1]),
                        high=float(c[2]),
                        low=float(c[3]),
                        close=float(c[4]),
                        volume=float(c[5]),
                    )
                )
        return candles
    except ccxt.BadSymbol as exc:
        raise ExchangeError(f"Símbolo '{symbol}' inválido ou indisponível na exchange '{exchange.id}': {exc}") from exc
    except (ccxt.NetworkError, ccxt.RequestTimeout, ccxt.ExchangeNotAvailable) as exc:
        raise ExchangeError(f"Erro de conexão/rede ao consultar candles na exchange '{exchange.id}': {exc}") from exc
    except ccxt.ExchangeError as exc:
        raise ExchangeError(f"Erro da exchange '{exchange.id}' ao consultar candles: {exc}") from exc
    except ccxt.BaseError as exc:
        raise ExchangeError(f"Erro geral no CCXT ao consultar candles: {exc}") from exc


def close_exchange(exchange: ccxt.Exchange) -> None:
    """Encerra graciosamente recursos de rede da exchange se aplicável."""
    if hasattr(exchange, "close"):
        try:
            exchange.close()
        except Exception:
            pass
