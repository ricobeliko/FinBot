"""Ponto de entrada do FinBot para a FASE 3 (Strategy Engine)."""

import sys

from finbot.config import Config, get_config
from finbot.exchange import (
    ExchangeError,
    close_exchange,
    create_exchange,
    fetch_candles,
    fetch_ticker,
)
from finbot.logging_setup import setup_logging
from finbot.strategy import evaluate_sma_crossover


def run(config: Config) -> int:
    """Executa o ciclo de vida da aplicação (Market Monitor + Strategy Engine)."""
    logger = setup_logging(log_level=config.log_level)

    # Exibição inicial
    print(f"{config.app_name}", flush=True)
    print(f"Environment: {config.environment}", flush=True)
    print(f"Trading mode: {config.trading_mode}", flush=True)
    print("Status: running", flush=True)
    print(flush=True)

    logger.info("FinBot started.")
    logger.info("Environment: %s.", config.environment)
    logger.info("Trading mode: %s.", config.trading_mode)
    logger.info(
        "Iniciando Market Monitor na exchange '%s' para '%s'.",
        config.exchange_id,
        config.symbol,
    )

    print(f"Exchange: {config.exchange_id}", flush=True)
    print(f"Symbol: {config.symbol}", flush=True)
    print(flush=True)

    exchange = create_exchange(config.exchange_id)
    try:
        # Consulta de ticker público
        ticker = fetch_ticker(exchange, config.symbol)
        logger.info(
            "Ticker obtido com sucesso para %s. Último preço: %s.",
            ticker.symbol,
            ticker.last,
        )

        print(f"Last price: {ticker.last}", flush=True)

        # Consulta de candles públicos
        candles = fetch_candles(
            exchange,
            symbol=config.symbol,
            timeframe=config.timeframe,
            limit=config.candle_limit,
        )
        logger.info(
            "%d candles obtidos com sucesso (%s).",
            len(candles),
            config.timeframe,
        )
        print(f"Candles loaded: {len(candles)}", flush=True)
        print(flush=True)

        # Avaliação da estratégia determinística (SMA Crossover)
        logger.info(
            "Executando estratégia SMA Crossover (%d/%d)...",
            config.short_window,
            config.long_window,
        )
        result = evaluate_sma_crossover(
            candles,
            short_window=config.short_window,
            long_window=config.long_window,
        )
        logger.info(
            "Estratégia executada. Sinal: %s. Motivo: %s.",
            result.signal.value,
            result.reason,
        )

        print("Strategy:", flush=True)
        print(f"SMA {config.short_window} / SMA {config.long_window}", flush=True)
        print(flush=True)

        short_ma_str = f"{result.short_ma:.2f}" if result.short_ma is not None else "N/A"
        long_ma_str = f"{result.long_ma:.2f}" if result.long_ma is not None else "N/A"
        print(f"Short MA: {short_ma_str}", flush=True)
        print(f"Long MA: {long_ma_str}", flush=True)
        print(flush=True)

        print(f"Signal: {result.signal.value}", flush=True)
        print(f"Reason: {result.reason}", flush=True)
        print(flush=True)

        print("Trading: disabled", flush=True)
    finally:
        close_exchange(exchange)

    logger.info("FinBot stopped.")
    return 0


def main(config: Config | None = None) -> int:
    """Função principal com tratamento gracioso de erros e interrupções."""
    try:
        active_config = config if config is not None else get_config()
        return run(active_config)
    except ExchangeError as exc:
        print(f"\nErro no Market Monitor: {exc}", file=sys.stderr, flush=True)
        logger = setup_logging()
        logger.error("Erro no Market Monitor: %s", exc)
        logger.info("FinBot stopped.")
        return 1
    except ValueError as exc:
        print(f"\nErro de configuração da estratégia: {exc}", file=sys.stderr, flush=True)
        logger = setup_logging()
        logger.error("Erro de configuração da estratégia: %s", exc)
        logger.info("FinBot stopped.")
        return 1
    except KeyboardInterrupt:
        print("\nOperação interrompida pelo usuário.", flush=True)
        return 0
    except Exception as exc:
        print(f"Erro inesperado durante a execução: {exc}", file=sys.stderr, flush=True)
        logger = setup_logging()
        logger.exception("Erro inesperado durante a execução: %s", exc)
        logger.info("FinBot stopped.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
