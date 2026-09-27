"""Script utilitário independente para download paginado e validação de datasets históricos.

Utiliza exclusivamente a API pública da exchange (sem chaves, sem credenciais, sem ordens)
para coletar sequências longas de candles fechados para pesquisa no FinBot Lab.
"""

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
import time

from finbot.backtest import DatasetMetadata, save_dataset_snapshot
from finbot.exchange import CandleData, close_exchange, create_exchange


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download paginado e validação de histórico público de candles."
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default="BTC/USDT",
        help="Par de negociação (padrão: BTC/USDT)",
    )
    parser.add_argument(
        "--timeframe",
        type=str,
        default="5m",
        help="Timeframe dos candles (padrão: 5m)",
    )
    parser.add_argument(
        "--candles",
        type=int,
        default=10000,
        help="Quantidade total de candles desejada (padrão: 10000)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/backtest/binance_BTCUSDT_5m_10000.json",
        help="Caminho do arquivo JSON de destino",
    )
    parser.add_argument(
        "--exchange",
        type=str,
        default="binance",
        help="Identificador da exchange no CCXT (padrão: binance)",
    )
    return parser.parse_args()


def timeframe_to_milliseconds(timeframe: str) -> int:
    """Converte string de timeframe simples (ex: '1m', '5m', '1h') para milissegundos."""
    unit = timeframe[-1]
    val = int(timeframe[:-1])
    if unit == "m":
        return val * 60 * 1000
    elif unit == "h":
        return val * 60 * 60 * 1000
    elif unit == "d":
        return val * 24 * 60 * 60 * 1000
    raise ValueError(f"Timeframe não suportado: {timeframe}")


def fetch_paginated_history(
    exchange_id: str,
    symbol: str,
    timeframe: str,
    total_candles: int,
) -> list[CandleData]:
    """Coleta candles históricos de forma paginada respeitando rate limits da exchange."""
    step_ms = timeframe_to_milliseconds(timeframe)
    ex = create_exchange(exchange_id)

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    # Define timestamp inicial estimado para cobrir os total_candles com folga de segurança
    # Adicionamos 200 candles de margem para compensar eventuais gaps ou candles em formação
    estimated_span_ms = (total_candles + 200) * step_ms
    start_since = now_ms - estimated_span_ms

    raw_candles_map: dict[int, list] = {}
    current_since = start_since
    batch_limit = 1000  # Limite máximo padrão do endpoint público da Binance

    print(
        f"Iniciando coleta paginada de {total_candles} candles de {timeframe} para {symbol} na {exchange_id}..."
    )

    try:
        while True:
            # Consulta pública sem autenticação
            ohlcv_batch = ex.fetch_ohlcv(symbol, timeframe, since=current_since, limit=batch_limit)
            if not ohlcv_batch:
                print("Nenhum dado adicional retornado pela exchange. Finalizando paginação.")
                break

            for row in ohlcv_batch:
                ts = int(row[0])
                # Descarta candle em formação (se ainda não fechou)
                if ts + step_ms > now_ms:
                    continue
                raw_candles_map[ts] = row

            first_ts = ohlcv_batch[0][0]
            last_ts = ohlcv_batch[-1][0]
            print(
                f"  Lote recebido: {len(ohlcv_batch)} candles "
                f"({datetime.fromtimestamp(first_ts / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')} -> "
                f"{datetime.fromtimestamp(last_ts / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')}). "
                f"Total acumulado: {len(raw_candles_map)}"
            )

            # Se já cobrimos até o tempo presente ou o lote veio vazio/menor que esperado
            if last_ts + step_ms >= now_ms or len(ohlcv_batch) < 10:
                break

            # Avança o cursor para o candle seguinte
            next_since = last_ts + step_ms
            if next_since <= current_since:
                # Previne loop infinito se a exchange retornar o mesmo timestamp
                next_since = current_since + step_ms
            current_since = next_since

            # Rate limit gentil e conservador
            time.sleep(0.25)

            # Se já acumulamos candles suficientes para recortar os últimos total_candles
            if len(raw_candles_map) >= total_candles + 100:
                break
    finally:
        close_exchange(ex)

    # Ordena por timestamp
    sorted_timestamps = sorted(raw_candles_map.keys())
    if len(sorted_timestamps) < total_candles:
        print(
            f"[AVISO] Quantidade coletada ({len(sorted_timestamps)}) foi menor que o solicitado ({total_candles})."
        )
        selected_timestamps = sorted_timestamps
    else:
        # Pega exatamente os últimos total_candles
        selected_timestamps = sorted_timestamps[-total_candles:]

    candles: list[CandleData] = []
    for ts in selected_timestamps:
        row = raw_candles_map[ts]
        candles.append(
            CandleData(
                timestamp=int(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
            )
        )

    return candles


def validate_candles_integrity(candles: list[CandleData], timeframe_str: str) -> None:
    """Valida monotonicidade, ausência de duplicatas, intervalo de 5m e integridade OHLCV."""
    if not candles:
        raise ValueError("Lista de candles vazia!")

    step_ms = timeframe_to_milliseconds(timeframe_str)
    seen_timestamps: set[int] = set()

    for idx, c in enumerate(candles):
        # Validação de duplicatas
        if c.timestamp in seen_timestamps:
            raise ValueError(f"Timestamp duplicado detectado no índice {idx}: {c.timestamp}")
        seen_timestamps.add(c.timestamp)

        # Validação de monotonicidade
        if idx > 0:
            prev_ts = candles[idx - 1].timestamp
            if c.timestamp <= prev_ts:
                raise ValueError(
                    f"Violação de monotonicidade no índice {idx}: {c.timestamp} <= {prev_ts}"
                )
            diff = c.timestamp - prev_ts
            if diff != step_ms:
                # Loga espaçamento irregular (pode ser manutenção da exchange)
                print(f"[ALERTA DE GAP] Descontinuidade temporal entre candle {idx-1} e {idx}: salto de {diff/60000:.1f} minutos.")

        # Validação geométrica do candle OHLC
        if c.high < c.low:
            raise ValueError(f"Candle inválido no índice {idx}: High ({c.high}) < Low ({c.low})")
        if c.high < c.open or c.high < c.close:
            raise ValueError(f"Candle inválido no índice {idx}: High menor que Open/Close ({c})")
        if c.low > c.open or c.low > c.close:
            raise ValueError(f"Candle inválido no índice {idx}: Low maior que Open/Close ({c})")
        if c.volume < 0:
            raise ValueError(f"Volume negativo no índice {idx}: {c.volume}")

    print(f"[OK] Integridade de {len(candles)} candles auditada com sucesso.")


def main() -> None:
    args = parse_arguments()
    out_path = Path(args.output)

    if out_path.exists():
        print(f"[AVISO] O arquivo de destino {out_path} já existe. Será sobrescrito.")

    candles = fetch_paginated_history(
        exchange_id=args.exchange,
        symbol=args.symbol,
        timeframe=args.timeframe,
        total_candles=args.candles,
    )

    if not candles:
        print("[ERRO] Nenhum candle foi coletado.", file=sys.stderr)
        sys.exit(1)

    validate_candles_integrity(candles, args.timeframe)

    metadata = DatasetMetadata(
        exchange=args.exchange,
        symbol=args.symbol,
        timeframe=args.timeframe,
        candle_count=len(candles),
        start_timestamp=candles[0].timestamp,
        end_timestamp=candles[-1].timestamp,
        start_datetime=candles[0].formatted_time,
        end_datetime=candles[-1].formatted_time,
        downloaded_at=datetime.now(timezone.utc).isoformat(),
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    save_dataset_snapshot(out_path, metadata, candles)

    print("\n==================================================")
    print("Snapshot Histórico Salvo com Sucesso")
    print("==================================================")
    print(f"Arquivo:    {out_path}")
    print(f"Símbolo:    {metadata.symbol}")
    print(f"Timeframe:  {metadata.timeframe}")
    print(f"Candles:    {metadata.candle_count}")
    print(f"Período:    {metadata.start_datetime} -> {metadata.end_datetime}")
    print(f"Origem:     {metadata.exchange} (endpoint público)")
    print(f"Tamanho:    {out_path.stat().st_size / 1024:.1f} KB")
    print("==================================================\n")


if __name__ == "__main__":
    main()
