"""Comando operacional estritamente read-only para consulta de status e métricas do Testnet Soak (FASE 8.4C2D).

Entrypoint:
    python -m finbot.testnet_soak_status

Zero ordens enviadas, zero chaves privadas expostas e zero mutação patrimonial.
"""

import argparse
import sys
from finbot.testnet_soak import print_testnet_soak_status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FinBot — Binance Spot Testnet Soak Status (Read-Only)")
    parser.add_argument("--db-path", type=str, default="data/finbot_testnet_soak.sqlite3", help="Caminho do banco SQLite do Soak.")
    args = parser.parse_args(argv)
    return print_testnet_soak_status(db_path=args.db_path)


if __name__ == "__main__":
    sys.exit(main())
