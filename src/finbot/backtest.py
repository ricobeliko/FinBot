"""Motor de backtesting reproduzível do FinBot para a FASE 4.

Adapta a engine Backtesting.py para executar a estratégia oficial
(finbot.strategy.evaluate_sma_crossover) sobre dados históricos locais.
Simulação estritamente local (SIMULATION ONLY). Nenhuma ordem real é emitida.
"""

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Sequence
import numpy as np
import pandas as pd
from backtesting import Strategy
from backtesting.lib import FractionalBacktest

from finbot.config import get_config
from finbot.exchange import CandleData, close_exchange, create_exchange, fetch_candles
from finbot.strategy import Signal, evaluate_sma_crossover


@dataclass(frozen=True)
class DatasetMetadata:
    """Metadados de identificação e reprodutibilidade do dataset histórico."""

    exchange: str
    symbol: str
    timeframe: str
    candle_count: int
    start_timestamp: int
    end_timestamp: int
    start_datetime: str
    end_datetime: str
    downloaded_at: str


@dataclass(frozen=True)
class BacktestResult:
    """Métricas consolidadas de performance do backtest."""

    initial_cash: float
    final_equity: float
    total_return_pct: float
    buy_and_hold_pct: float
    trades_count: int
    wins: int
    losses: int
    win_rate_pct: float | None
    max_drawdown_pct: float
    profit_factor: float | None


class FinBotSMAStrategy(Strategy):
    """Adaptador que conecta a engine Backtesting.py à estratégia oficial do FinBot.

    NÃO duplica a lógica de médias móveis. Apenas delega a avaliação a
    `finbot.strategy.evaluate_sma_crossover` passando os fechamentos conhecidos até o momento.

    Premissas do Modelo de Simulação (FASE 4):
    - Spot LONG only: BUY abre posição se não houver posição; SELL fecha posição existente.
    - HOLD: não faz nada.
    - Sem posições vendidas (short), sem alavancagem, sem futuros e sem margin.
    - No máximo uma posição por vez.
    - Sem look-ahead: a decisão é tomada no fechamento de t e executada pela engine
      no próximo candle (t+1 Open).
    """

    short_window: int = 5
    long_window: int = 10

    def init(self) -> None:
        """Inicialização da estratégia no Backtesting.py.

        Não pré-calculamos indicadores de forma vetorizada para garantir semântica
        passo-a-passo idêntica à estratégia em tempo de execução.
        """

    def next(self) -> None:
        """Executado a cada novo candle na ordem cronológica estrita.

        self.data.Close contém exclusivamente os candles conhecidos até o instante t atual.
        Fatiamos apenas os últimos (long_window + 1) candles necessários para eliminar
        complexidade quadrática O(N^2) sobre séries longas, mantendo semântica estrita.
        """
        required_candles = self.long_window + 1
        closes = self.data.Close[-required_candles:]
        result = evaluate_sma_crossover(
            data=closes,
            short_window=self.short_window,
            long_window=self.long_window,
        )

        if result.signal == Signal.BUY:
            if not self.position:
                self.buy()
        elif result.signal == Signal.SELL:
            if self.position:
                self.position.close()
        # Signal.HOLD: nenhuma ação


def candles_to_dataframe(candles: Sequence[Any]) -> pd.DataFrame:
    """Converte sequência de candles em DataFrame estruturado para o Backtesting.py.

    O Backtesting.py exige colunas com nomes capitalizados:
    'Open', 'High', 'Low', 'Close', 'Volume' e DatetimeIndex.
    """
    if not candles:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

    rows = []
    timestamps = []
    for c in candles:
        if isinstance(c, CandleData):
            ts = c.timestamp
            rows.append({
                "Open": c.open,
                "High": c.high,
                "Low": c.low,
                "Close": c.close,
                "Volume": c.volume,
            })
        elif isinstance(c, dict):
            ts = c["timestamp"]
            rows.append({
                "Open": float(c["open"]),
                "High": float(c["high"]),
                "Low": float(c["low"]),
                "Close": float(c["close"]),
                "Volume": float(c["volume"]),
            })
        else:
            ts = getattr(c, "timestamp")
            rows.append({
                "Open": float(getattr(c, "open")),
                "High": float(getattr(c, "high")),
                "Low": float(getattr(c, "low")),
                "Close": float(getattr(c, "close")),
                "Volume": float(getattr(c, "volume")),
            })
        timestamps.append(ts)

    df = pd.DataFrame(rows)
    df.index = pd.to_datetime(timestamps, unit="ms", utc=True)
    df.index.name = "Date"
    return df


def save_dataset_snapshot(
    filepath: str | Path,
    metadata: DatasetMetadata,
    candles: Sequence[CandleData],
) -> None:
    """Salva snapshot histórico em arquivo JSON para garantir reprodutibilidade."""
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "exchange": metadata.exchange,
        "symbol": metadata.symbol,
        "timeframe": metadata.timeframe,
        "candle_count": metadata.candle_count,
        "start_timestamp": metadata.start_timestamp,
        "end_timestamp": metadata.end_timestamp,
        "start_datetime": metadata.start_datetime,
        "end_datetime": metadata.end_datetime,
        "downloaded_at": metadata.downloaded_at,
        "candles": [
            {
                "timestamp": c.timestamp,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
            }
            for c in candles
        ],
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_dataset_snapshot(filepath: str | Path) -> tuple[DatasetMetadata, list[CandleData]]:
    """Carrega snapshot histórico previamente salvo em arquivo JSON."""
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Arquivo de snapshot não encontrado: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    metadata = DatasetMetadata(
        exchange=data["exchange"],
        symbol=data["symbol"],
        timeframe=data["timeframe"],
        candle_count=data["candle_count"],
        start_timestamp=data["start_timestamp"],
        end_timestamp=data["end_timestamp"],
        start_datetime=data["start_datetime"],
        end_datetime=data["end_datetime"],
        downloaded_at=data["downloaded_at"],
    )

    candles = [
        CandleData(
            timestamp=c["timestamp"],
            open=float(c["open"]),
            high=float(c["high"]),
            low=float(c["low"]),
            close=float(c["close"]),
            volume=float(c["volume"]),
        )
        for c in data["candles"]
    ]

    return metadata, candles


def load_or_fetch_dataset(
    exchange_id: str = "binance",
    symbol: str = "BTC/USDT",
    timeframe: str = "5m",
    limit: int = 500,
    data_dir: str = "data/backtest",
    force_download: bool = False,
) -> tuple[DatasetMetadata, pd.DataFrame]:
    """Carrega o snapshot histórico local se já existir, ou baixa uma única vez.

    Garante que backtests subsequentes sejam 100% reproduzíveis sobre os mesmos dados.
    """
    clean_symbol = symbol.replace("/", "").replace(":", "")
    snapshot_filename = f"{exchange_id.lower()}_{clean_symbol}_{timeframe}.json"
    snapshot_path = Path(data_dir) / snapshot_filename

    if snapshot_path.exists() and not force_download:
        metadata, candles = load_dataset_snapshot(snapshot_path)
        df = candles_to_dataframe(candles)
        return metadata, df

    # Download uma única vez via endpoint público da exchange
    ex = create_exchange(exchange_id)
    try:
        candles = fetch_candles(ex, symbol=symbol, timeframe=timeframe, limit=limit)
    finally:
        close_exchange(ex)

    if not candles:
        raise ValueError(f"Nenhum candle retornado pela exchange {exchange_id} para {symbol}")

    downloaded_at = datetime.now(timezone.utc).isoformat()
    metadata = DatasetMetadata(
        exchange=exchange_id,
        symbol=symbol,
        timeframe=timeframe,
        candle_count=len(candles),
        start_timestamp=candles[0].timestamp,
        end_timestamp=candles[-1].timestamp,
        start_datetime=candles[0].formatted_time,
        end_datetime=candles[-1].formatted_time,
        downloaded_at=downloaded_at,
    )

    save_dataset_snapshot(snapshot_path, metadata, candles)
    df = candles_to_dataframe(candles)
    return metadata, df


def run_backtest(
    df: pd.DataFrame,
    initial_cash: float = 10000.0,
    commission: float = 0.001,
    short_window: int = 5,
    long_window: int = 10,
) -> BacktestResult:
    """Executa a simulação histórica reproduzível da estratégia.

    Parâmetros:
    - df: DataFrame com colunas Open, High, Low, Close, Volume e DatetimeIndex.
    - initial_cash: Capital inicial simulado em USDT.
    - commission: Taxa proporcional simulada por operação (ex: 0.001 = 0.10%).
    - short_window: Período da SMA curta.
    - long_window: Período da SMA longa.
    """
    required_candles = long_window + 1
    if len(df) < required_candles:
        raise ValueError(
            f"Dataset insuficiente para backtest: {len(df)} candles fornecidos, "
            f"necessário pelo menos {required_candles} (long_window + 1)."
        )

    class ConfiguredStrategy(FinBotSMAStrategy):
        pass

    ConfiguredStrategy.short_window = short_window
    ConfiguredStrategy.long_window = long_window

    bt = FractionalBacktest(
        df,
        ConfiguredStrategy,
        cash=initial_cash,
        commission=commission,
        finalize_trades=True,
    )

    stats = bt.run()

    trades_df = stats.get("_trades")
    trades_count = int(stats.get("# Trades", 0))

    wins = 0
    losses = 0
    if trades_df is not None and len(trades_df) > 0:
        wins = int((trades_df["PnL"] > 0).sum())
        losses = int((trades_df["PnL"] < 0).sum())

    raw_win_rate = stats.get("Win Rate [%]")
    win_rate_pct = None if (raw_win_rate is None or pd.isna(raw_win_rate)) else float(raw_win_rate)

    raw_pf = stats.get("Profit Factor")
    profit_factor = None if (raw_pf is None or pd.isna(raw_pf) or np.isinf(raw_pf)) else float(raw_pf)

    return BacktestResult(
        initial_cash=float(initial_cash),
        final_equity=float(stats.get("Equity Final [$]", initial_cash)),
        total_return_pct=float(stats.get("Return [%]", 0.0)),
        buy_and_hold_pct=float(stats.get("Buy & Hold Return [%]", 0.0)),
        trades_count=trades_count,
        wins=wins,
        losses=losses,
        win_rate_pct=win_rate_pct,
        max_drawdown_pct=float(stats.get("Max. Drawdown [%]", 0.0)),
        profit_factor=profit_factor,
    )


def format_backtest_report(
    metadata: DatasetMetadata,
    result: BacktestResult,
    short_window: int = 5,
    long_window: int = 10,
    commission: float = 0.001,
) -> str:
    """Formata o relatório textual simples no padrão especificado para o terminal.

    Sem adjetivação ou recomendações financeiras. Apenas números e métricas puras.
    """
    win_rate_str = f"{result.win_rate_pct:.2f}%" if result.win_rate_pct is not None else "N/A"
    profit_factor_str = f"{result.profit_factor:.2f}" if result.profit_factor is not None else "N/A"
    commission_pct = commission * 100.0

    lines = [
        "==================================================",
        "FinBot Backtest",
        "==================================================",
        "",
        f"Exchange: {metadata.exchange}",
        f"Symbol: {metadata.symbol}",
        f"Timeframe: {metadata.timeframe}",
        f"Candles: {metadata.candle_count}",
        f"Period: {metadata.start_datetime} -> {metadata.end_datetime}",
        "",
        "Strategy:",
        f"SMA {short_window} / SMA {long_window}",
        "",
        "Initial cash:",
        f"{result.initial_cash:.2f} USDT",
        "",
        "Commission assumption:",
        f"{commission_pct:.2f}% (simulation assumption)",
        "",
        "Results:",
        "",
        f"Final equity: {result.final_equity:.2f} USDT",
        f"Return: {result.total_return_pct:+.2f}%",
        f"Buy & Hold: {result.buy_and_hold_pct:+.2f}%",
        f"Trades: {result.trades_count} (Wins: {result.wins}, Losses: {result.losses})",
        f"Win rate: {win_rate_str}",
        f"Max drawdown: {result.max_drawdown_pct:.2f}%",
        f"Profit factor: {profit_factor_str}",
        "",
        "Trading mode:",
        "SIMULATION ONLY",
        "",
        "No real orders were sent.",
        "==================================================",
    ]
    return "\n".join(lines)


def main() -> None:
    """Ponto de entrada para execução de backtest via CLI."""
    parser = argparse.ArgumentParser(description="FinBot Backtest Engine (FASE 4)")
    parser.add_argument("--refresh", action="store_true", help="Força novo download do dataset histórico")
    parser.add_argument("--symbol", type=str, default=None, help="Símbolo a simular (padrão: config)")
    parser.add_argument("--timeframe", type=str, default=None, help="Timeframe (padrão: config)")
    parser.add_argument("--candles", type=int, default=None, help="Quantidade de candles (padrão: config)")
    args = parser.parse_args()

    config = get_config()
    symbol = args.symbol or config.symbol
    timeframe = args.timeframe or config.backtest_timeframe
    candle_limit = args.candles or config.backtest_candle_limit
    data_dir = config.backtest_data_dir

    metadata, df = load_or_fetch_dataset(
        exchange_id=config.exchange_id,
        symbol=symbol,
        timeframe=timeframe,
        limit=candle_limit,
        data_dir=data_dir,
        force_download=args.refresh,
    )

    result = run_backtest(
        df=df,
        initial_cash=config.backtest_initial_cash,
        commission=config.backtest_commission,
        short_window=config.short_window,
        long_window=config.long_window,
    )

    report = format_backtest_report(
        metadata=metadata,
        result=result,
        short_window=config.short_window,
        long_window=config.long_window,
        commission=config.backtest_commission,
    )
    print(report)


if __name__ == "__main__":
    main()
