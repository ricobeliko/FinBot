"""Ponto de entrada do FinBot para a FASE 1 (Python Core)."""

import sys

from finbot.config import Config, get_config
from finbot.logging_setup import setup_logging


def run(config: Config) -> int:
    """Executa o ciclo de vida da aplicação (startup e shutdown)."""
    logger = setup_logging(log_level=config.log_level)

    # Saída clara e direta de inicialização no console
    print(f"{config.app_name}", flush=True)
    print(f"Environment: {config.environment}", flush=True)
    print(f"Trading mode: {config.trading_mode}", flush=True)
    print("Status: running", flush=True)

    # Registro de log de inicialização
    logger.info("FinBot started.")
    logger.info("Environment: %s.", config.environment)
    logger.info("Trading mode: %s.", config.trading_mode)

    # Finalização limpa (Fase 1 não possui loop de mercado ou chamadas externas)
    logger.info("FinBot stopped.")
    return 0


def main() -> int:
    """Função principal com tratamento de interrupção e exceções."""
    try:
        config = get_config()
        return run(config)
    except KeyboardInterrupt:
        print("\nOperação interrompida pelo usuário.")
        return 0
    except Exception as exc:
        print(f"Erro inesperado durante a execução: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
