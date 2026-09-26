"""Camada de persistência local SQLite para Paper Trading (FASE 5).

Utiliza estritamente a biblioteca sqlite3 da Python Standard Library.
Garante atomicidade (ACID) em todas as operações da conta e histórico de trades.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import sqlite3
from typing import Generator


@dataclass(frozen=True)
class PaperAccount:
    """Saldo consolidado da conta simulada de Paper Trading."""

    usdt_balance: Decimal
    btc_balance: Decimal
    updated_at: str


@dataclass(frozen=True)
class PaperPosition:
    """Estado da posição simulada atual (Spot LONG ou NONE)."""

    side: str  # "LONG" ou "NONE"
    quantity: Decimal  # Quantidade de BTC
    cost_basis: Decimal  # Custo total em USDT (incluindo taxa de entrada)
    entry_price: Decimal  # Preço unitário na abertura
    entry_timestamp: str  # Data/hora ISO8601 da abertura


@dataclass(frozen=True)
class PaperTrade:
    """Registro imutável de uma operação simulada executada."""

    id: int | None
    timestamp: str
    candle_timestamp: int
    symbol: str
    side: str  # "BUY" ou "SELL"
    price: Decimal
    quantity: Decimal
    notional: Decimal
    fee: Decimal
    realized_pnl: Decimal | None


class PaperStorage:
    """Gerenciador de persistência SQLite para Paper Trading."""

    def __init__(self, db_path: str | Path = "data/finbot_paper.sqlite3", timeout: float = 30.0) -> None:
        self.db_path = Path(db_path)
        self.timeout = timeout

    def get_connection(self) -> sqlite3.Connection:
        """Abre conexão SQLite garantindo criação de diretórios e timeouts adequados."""
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=self.timeout)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Abre conexão SQLite e garante commit e fechamento explícito do handle."""
        conn = self.get_connection()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def init_db(self, initial_cash: Decimal = Decimal("10000.00")) -> None:
        """Inicializa as tabelas do banco e cria os registros padrão se não existirem."""
        with self.connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS paper_account (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    usdt_balance TEXT NOT NULL,
                    btc_balance TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS paper_position (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    side TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    cost_basis TEXT NOT NULL,
                    entry_price TEXT NOT NULL,
                    entry_timestamp TEXT NOT NULL
                );
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS paper_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    candle_timestamp INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    price TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    notional TEXT NOT NULL,
                    fee TEXT NOT NULL,
                    realized_pnl TEXT
                );
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS paper_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
            """)

            # Seed account se vazia
            cur = conn.execute("SELECT COUNT(*) FROM paper_account;")
            if cur.fetchone()[0] == 0:
                now_iso = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    "INSERT INTO paper_account (id, usdt_balance, btc_balance, updated_at) VALUES (1, ?, ?, ?);",
                    (str(initial_cash), "0.00000000", now_iso),
                )

            # Seed position se vazia
            cur = conn.execute("SELECT COUNT(*) FROM paper_position;")
            if cur.fetchone()[0] == 0:
                conn.execute(
                    "INSERT INTO paper_position (id, side, quantity, cost_basis, entry_price, entry_timestamp) "
                    "VALUES (1, 'NONE', '0.00000000', '0.00', '0.00', '');"
                )

    def get_account(self) -> PaperAccount:
        """Retorna o saldo atual da conta paper."""
        with self.connection() as conn:
            cur = conn.execute("SELECT usdt_balance, btc_balance, updated_at FROM paper_account WHERE id = 1;")
            row = cur.fetchone()
            if not row:
                raise RuntimeError("Conta de Paper Trading não inicializada.")
            return PaperAccount(
                usdt_balance=Decimal(row["usdt_balance"]),
                btc_balance=Decimal(row["btc_balance"]),
                updated_at=row["updated_at"],
            )

    def get_position(self) -> PaperPosition:
        """Retorna o estado da posição atual."""
        with self.connection() as conn:
            cur = conn.execute(
                "SELECT side, quantity, cost_basis, entry_price, entry_timestamp FROM paper_position WHERE id = 1;"
            )
            row = cur.fetchone()
            if not row:
                raise RuntimeError("Posição de Paper Trading não inicializada.")
            return PaperPosition(
                side=row["side"],
                quantity=Decimal(row["quantity"]),
                cost_basis=Decimal(row["cost_basis"]),
                entry_price=Decimal(row["entry_price"]),
                entry_timestamp=row["entry_timestamp"],
            )

    def get_last_processed_candle_timestamp(self) -> int | None:
        """Retorna o timestamp (ms) do último candle fechado processado pela estratégia."""
        with self.connection() as conn:
            cur = conn.execute("SELECT value FROM paper_state WHERE key = 'last_processed_candle_timestamp';")
            row = cur.fetchone()
            if row:
                return int(row["value"])
            return None

    def record_candle_processed(self, candle_timestamp: int) -> None:
        """Atualiza o timestamp do último candle processado quando não há execução de trade."""
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO paper_state (key, value) VALUES ('last_processed_candle_timestamp', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value;",
                (str(candle_timestamp),),
            )

    def get_trades(self, limit: int = 100) -> list[PaperTrade]:
        """Retorna histórico de trades simulados em ordem decrescente."""
        with self.connection() as conn:
            cur = conn.execute(
                "SELECT id, timestamp, candle_timestamp, symbol, side, price, quantity, notional, fee, realized_pnl "
                "FROM paper_trades ORDER BY id DESC LIMIT ?;",
                (limit,),
            )
            rows = cur.fetchall()
            return [
                PaperTrade(
                    id=r["id"],
                    timestamp=r["timestamp"],
                    candle_timestamp=r["candle_timestamp"],
                    symbol=r["symbol"],
                    side=r["side"],
                    price=Decimal(r["price"]),
                    quantity=Decimal(r["quantity"]),
                    notional=Decimal(r["notional"]),
                    fee=Decimal(r["fee"]),
                    realized_pnl=Decimal(r["realized_pnl"]) if r["realized_pnl"] is not None else None,
                )
                for r in rows
            ]

    def get_trades_count(self) -> int:
        """Retorna o número total de trades executados."""
        with self.connection() as conn:
            cur = conn.execute("SELECT COUNT(*) FROM paper_trades;")
            return int(cur.fetchone()[0])

    def get_last_trade(self) -> PaperTrade | None:
        """Retorna o último trade executado ou None se não houver."""
        trades = self.get_trades(limit=1)
        return trades[0] if trades else None

    def execute_trade_transaction(
        self,
        new_account: PaperAccount,
        new_position: PaperPosition,
        trade: PaperTrade,
        candle_timestamp: int,
    ) -> PaperTrade:
        """Executa uma transação atômica completa de trade simulado no SQLite.

        Atualiza em conjunto: saldo, posição, registro do trade e último candle processado.
        Qualquer falha intermediária dispara rollback automático.
        """
        with self.connection() as conn:
            # 1. Atualiza conta
            conn.execute(
                "UPDATE paper_account SET usdt_balance = ?, btc_balance = ?, updated_at = ? WHERE id = 1;",
                (str(new_account.usdt_balance), str(new_account.btc_balance), new_account.updated_at),
            )

            # 2. Atualiza posição
            conn.execute(
                "UPDATE paper_position SET side = ?, quantity = ?, cost_basis = ?, entry_price = ?, "
                "entry_timestamp = ? WHERE id = 1;",
                (
                    new_position.side,
                    str(new_position.quantity),
                    str(new_position.cost_basis),
                    str(new_position.entry_price),
                    new_position.entry_timestamp,
                ),
            )

            # 3. Insere trade
            cur = conn.execute(
                "INSERT INTO paper_trades (timestamp, candle_timestamp, symbol, side, price, quantity, "
                "notional, fee, realized_pnl) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                (
                    trade.timestamp,
                    trade.candle_timestamp,
                    trade.symbol,
                    trade.side,
                    str(trade.price),
                    str(trade.quantity),
                    str(trade.notional),
                    str(trade.fee),
                    str(trade.realized_pnl) if trade.realized_pnl is not None else None,
                ),
            )
            trade_id = cur.lastrowid

            # 4. Atualiza estado do candle
            conn.execute(
                "INSERT INTO paper_state (key, value) VALUES ('last_processed_candle_timestamp', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value;",
                (str(candle_timestamp),),
            )

            return PaperTrade(
                id=trade_id,
                timestamp=trade.timestamp,
                candle_timestamp=trade.candle_timestamp,
                symbol=trade.symbol,
                side=trade.side,
                price=trade.price,
                quantity=trade.quantity,
                notional=trade.notional,
                fee=trade.fee,
                realized_pnl=trade.realized_pnl,
            )

    def reset_db(self, initial_cash: Decimal = Decimal("10000.00")) -> None:
        """Reseta integralmente o ambiente fictício de Paper Trading."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                "UPDATE paper_account SET usdt_balance = ?, btc_balance = '0.00000000', updated_at = ? WHERE id = 1;",
                (str(initial_cash), now_iso),
            )
            conn.execute(
                "UPDATE paper_position SET side = 'NONE', quantity = '0.00000000', cost_basis = '0.00', "
                "entry_price = '0.00', entry_timestamp = '' WHERE id = 1;"
            )
            conn.execute("DELETE FROM paper_trades;")
            conn.execute("DELETE FROM paper_state WHERE key = 'last_processed_candle_timestamp';")
