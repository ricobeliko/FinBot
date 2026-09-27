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
from typing import Any, Generator


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
    exit_reason: str | None = None


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
        """Inicializa as tabelas do banco e migra schema se necessário de forma idempotente."""
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
                    realized_pnl TEXT,
                    exit_reason TEXT
                );
            """)

            # Migração idempotente: adiciona coluna exit_reason se tabela já existia sem ela
            cur_cols = conn.execute("PRAGMA table_info(paper_trades);")
            col_names = [r["name"] for r in cur_cols.fetchall()]
            if "exit_reason" not in col_names:
                conn.execute("ALTER TABLE paper_trades ADD COLUMN exit_reason TEXT;")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS paper_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
            """)

            # Tabela de experiências (FASE 7.9E - Experience Dataset Foundation)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS experiences (
                    experience_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    decision_at TEXT NOT NULL,
                    candle_timestamp INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    price REAL NOT NULL,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL,
                    strategy_name TEXT NOT NULL,
                    strategy_version TEXT NOT NULL,
                    strategy_parameters TEXT NOT NULL,
                    signal TEXT NOT NULL,
                    signal_reason TEXT NOT NULL,
                    position_before TEXT NOT NULL,
                    risk_decision TEXT NOT NULL,
                    risk_reason TEXT NOT NULL,
                    risk_allowed INTEGER NOT NULL,
                    execution_price REAL,
                    execution_quantity REAL,
                    execution_fee REAL,
                    outcome_at TEXT,
                    exit_price REAL,
                    realized_pnl REAL,
                    realized_return REAL,
                    fees REAL,
                    mfe REAL,
                    mae REAL,
                    trade_duration REAL,
                    future_return_5 REAL,
                    future_return_20 REAL,
                    future_return_50 REAL,
                    future_return_100 REAL,
                    outcome TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(source, source_id)
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_experiences_source ON experiences(source);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_experiences_run_id ON experiences(run_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_experiences_decision_at ON experiences(decision_at);")

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
                "SELECT id, timestamp, candle_timestamp, symbol, side, price, quantity, notional, fee, realized_pnl, exit_reason "
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
                    exit_reason=r["exit_reason"] if "exit_reason" in r.keys() else None,
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
                "notional, fee, realized_pnl, exit_reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
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
                    trade.exit_reason,
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
                exit_reason=trade.exit_reason,
            )

    def set_kill_switch(self, active: bool) -> None:
        """Persiste o estado do kill switch no SQLite."""
        val = "1" if active else "0"
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO paper_state (key, value) VALUES ('kill_switch', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value;",
                (val,),
            )

    def get_kill_switch(self, default: bool = False) -> bool:
        """Consulta o estado persistido do kill switch no SQLite."""
        with self.connection() as conn:
            cur = conn.execute("SELECT value FROM paper_state WHERE key = 'kill_switch';")
            row = cur.fetchone()
            if row:
                return row["value"] == "1"
            return default

    def set_last_risk_block(self, code: str, reason: str) -> None:
        """Registra no SQLite o último bloqueio de trade emitido pelo Risk Engine."""
        now_iso = datetime.now(timezone.utc).isoformat()
        entry = f"{code}: {reason} ({now_iso})"
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO paper_state (key, value) VALUES ('last_risk_block', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value;",
                (entry,),
            )

    def get_last_risk_block(self) -> str | None:
        """Retorna a descrição e horário do último bloqueio de risco registrado."""
        with self.connection() as conn:
            cur = conn.execute("SELECT value FROM paper_state WHERE key = 'last_risk_block';")
            row = cur.fetchone()
            return row["value"] if row else None

    def get_last_closed_trade_candle_timestamp(self) -> int | None:
        """Retorna o timestamp (ms) do candle em que ocorreu o último fechamento de posição (SELL)."""
        with self.connection() as conn:
            cur = conn.execute(
                "SELECT candle_timestamp FROM paper_trades WHERE side = 'SELL' ORDER BY id DESC LIMIT 1;"
            )
            row = cur.fetchone()
            return int(row["candle_timestamp"]) if row else None

    def get_daily_realized_loss(self, date_utc: str | None = None) -> Decimal:
        """Retorna o P/L realizado consolidado das vendas no dia UTC informado."""
        if date_utc is None:
            date_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with self.connection() as conn:
            cur = conn.execute(
                "SELECT realized_pnl FROM paper_trades WHERE side = 'SELL' AND realized_pnl IS NOT NULL "
                "AND timestamp LIKE ?;",
                (f"{date_utc}%",),
            )
            rows = cur.fetchall()
            daily_pnl = Decimal("0.00")
            for r in rows:
                if r["realized_pnl"] is not None:
                    daily_pnl += Decimal(str(r["realized_pnl"]))
            return daily_pnl

    def record_signal(self, signal: str, reason: str, timestamp_iso: str) -> None:
        """Registra o último sinal avaliado da estratégia para consulta pelo Dashboard."""
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO paper_state (key, value) VALUES ('last_signal', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value;",
                (signal,),
            )
            conn.execute(
                "INSERT INTO paper_state (key, value) VALUES ('last_signal_reason', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value;",
                (reason,),
            )
            conn.execute(
                "INSERT INTO paper_state (key, value) VALUES ('last_signal_time', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value;",
                (timestamp_iso,),
            )

    def get_last_signal(self) -> dict[str, str] | None:
        """Retorna o último sinal da estratégia registrado no SQLite."""
        with self.connection() as conn:
            cur = conn.execute(
                "SELECT key, value FROM paper_state WHERE key IN ('last_signal', 'last_signal_reason', 'last_signal_time');"
            )
            rows = {r["key"]: r["value"] for r in cur.fetchall()}
            if "last_signal" in rows:
                return {
                    "signal": rows.get("last_signal", "HOLD"),
                    "reason": rows.get("last_signal_reason", ""),
                    "timestamp": rows.get("last_signal_time", ""),
                }
            return None

    def record_cycle_run(
        self,
        result: str,
        timestamp_iso: str,
        is_success: bool = True,
        message: str = "",
    ) -> None:
        """Registra informações do ciclo de execução do Paper Trading para observabilidade do Soak Test."""
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO paper_state (key, value) VALUES ('last_cycle_timestamp', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value;",
                (timestamp_iso,),
            )
            conn.execute(
                "INSERT INTO paper_state (key, value) VALUES ('last_cycle_result', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value;",
                (result,),
            )
            if message:
                conn.execute(
                    "INSERT INTO paper_state (key, value) VALUES ('last_cycle_message', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value;",
                    (message,),
                )

            # Inicializa soak_start_timestamp se ainda não existir
            conn.execute(
                "INSERT OR IGNORE INTO paper_state (key, value) VALUES ('soak_start_timestamp', ?);",
                (timestamp_iso,),
            )

            # Incrementa contador total de ciclos
            conn.execute(
                "INSERT INTO paper_state (key, value) VALUES ('total_cycles', '1') "
                "ON CONFLICT(key) DO UPDATE SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT);"
            )

            if is_success:
                conn.execute(
                    "INSERT INTO paper_state (key, value) VALUES ('last_successful_cycle_timestamp', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value;",
                    (timestamp_iso,),
                )
                conn.execute(
                    "INSERT INTO paper_state (key, value) VALUES ('successful_cycles', '1') "
                    "ON CONFLICT(key) DO UPDATE SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT);"
                )
                if result == "NO_NEW_CANDLE":
                    conn.execute(
                        "INSERT INTO paper_state (key, value) VALUES ('deduplicated_cycles', '1') "
                        "ON CONFLICT(key) DO UPDATE SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT);"
                    )
            else:
                conn.execute(
                    "INSERT INTO paper_state (key, value) VALUES ('failed_cycles', '1') "
                    "ON CONFLICT(key) DO UPDATE SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT);"
                )
                err_msg = message or result
                conn.execute(
                    "INSERT INTO paper_state (key, value) VALUES ('last_error', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value;",
                    (err_msg,),
                )
                conn.execute(
                    "INSERT INTO paper_state (key, value) VALUES ('last_error_timestamp', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value;",
                    (timestamp_iso,),
                )

    def get_last_cycle_info(self) -> dict[str, Any]:
        """Retorna dados de observabilidade do último ciclo e telemetria do Soak Test."""
        with self.connection() as conn:
            cur = conn.execute(
                "SELECT key, value FROM paper_state WHERE key IN ("
                "'last_cycle_timestamp', 'last_cycle_result', 'last_successful_cycle_timestamp', 'last_cycle_message', "
                "'soak_start_timestamp', 'total_cycles', 'successful_cycles', 'failed_cycles', 'deduplicated_cycles', "
                "'last_error', 'last_error_timestamp'"
                ");"
            )
            rows = {r["key"]: r["value"] for r in cur.fetchall()}
            return {
                "timestamp": rows.get("last_cycle_timestamp", ""),
                "result": rows.get("last_cycle_result", ""),
                "successful_timestamp": rows.get("last_successful_cycle_timestamp", ""),
                "message": rows.get("last_cycle_message", ""),
                "soak_start": rows.get("soak_start_timestamp", ""),
                "total_cycles": int(rows.get("total_cycles", "0")),
                "successful_cycles": int(rows.get("successful_cycles", "0")),
                "failed_cycles": int(rows.get("failed_cycles", "0")),
                "deduplicated_cycles": int(rows.get("deduplicated_cycles", "0")),
                "last_error": rows.get("last_error", ""),
                "last_error_timestamp": rows.get("last_error_timestamp", ""),
            }

    def reset_db(self, initial_cash: Decimal = Decimal("10000.00")) -> None:
        """Reseta integralmente o ambiente fictício de Paper Trading e o estado do Risk Engine."""
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
            conn.execute(
                "DELETE FROM paper_state WHERE key IN ("
                "'last_processed_candle_timestamp', 'kill_switch', 'last_risk_block', "
                "'last_signal', 'last_signal_reason', 'last_signal_time', "
                "'last_cycle_timestamp', 'last_cycle_result', 'last_successful_cycle_timestamp', 'last_cycle_message', "
                "'soak_start_timestamp', 'total_cycles', 'successful_cycles', 'failed_cycles', 'deduplicated_cycles', "
                "'last_error', 'last_error_timestamp');"
            )
