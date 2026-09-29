"""Comando operacional estritamente read-only para consulta de status e métricas do Testnet Soak (FASE 8.4C2D).

Entrypoint:
    python -m finbot.testnet_soak_status

Zero ordens enviadas, zero chaves privadas expostas e zero mutação patrimonial.
"""

import sys
from finbot.testnet_soak import print_testnet_soak_status


def main() -> int:
    return print_testnet_soak_status()


if __name__ == "__main__":
    sys.exit(main())
