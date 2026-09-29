"""Módulo de execução prolongada (Soak) e métricas operacionais na Binance Spot Testnet (FASE 8.4C2D).

Executa a estratégia continuamente em ambiente oficial de sandbox (testnet.binance.vision)
com capital fictício normalizado (TESTNET_STRATEGY_CAPITAL), mantendo observabilidade total,
circuit breakers defensivos, reconciliação mandatória e garantia absoluta de isolamento de produção.

NENHUMA ORDEM DE PRODUÇÃO É POSSÍVEL.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
import json
import logging
from pathlib import Path
import sqlite3
import sys
import threading
import time
from typing import Any

from finbot.config import Config, get_config
from finbot.credentials import WindowsCredentialProvider
from finbot.exchange import CandleData, close_exchange, create_exchange, fetch_candles, fetch_ticker
from finbot.execution import generate_client_order_id
from finbot.live_executor import (
    ApprovedOrderIntent,
    BinanceEnvironment,
    ExchangeOrderAdapter,
    ExchangeOrderResult,
    FakeExchangeOrderAdapter,
    GuardedLiveExecutionEngine,
    LiveOrderStorage,
    OrderStatus,
)
from finbot.live_safety import (
    AccountStateSnapshot,
    LiveSafetyGate,
    MarketFilterGuard,
    MarketFilters,
    OrderIntent,
    extract_market_filters,
    sanitize_amount,
)
from finbot.logging_setup import setup_logging
from finbot.paper import filter_closed_candles
from finbot.risk import RiskDecision, RiskDecisionCode, RiskEngine
from finbot.storage import PaperAccount, PaperPosition
from finbot.strategy import Signal, evaluate_sma_crossover
from finbot.testnet_adapter import BinanceSpotTestnetOrderAdapter

logger = logging.getLogger("finbot.testnet_soak")

SYMBOL_BTC_USDT = "BTC/USDT"
TARGET_NAME_TESTNET = "FinBot/Binance/SpotTestnet"
TARGET_NAME_PRODUCTION = "FinBot/Binance/Production"
TESTNET_DOMAIN = "testnet.binance.vision"
PRODUCTION_DOMAIN = "api.binance.com"

DEFAULT_STRATEGY_CAPITAL = Decimal("100.00")
DEFAULT_TARGET_MICRO_ORDER_NOTIONAL = Decimal("6.00")


# =============================================================================
# EXCEÇÕES DE SEGURANÇA E CIRCUIT BREAKERS
# =============================================================================

class TestnetSoakSentryError(Exception):
    """Lançada quando qualquer sentry de segurança do Testnet Soak é violado."""


class CircuitBreakerTrippedError(Exception):
    """Lançada quando uma nova ordem é solicitada com circuit breaker armado."""


# =============================================================================
# CIRCUIT BREAKER SYSTEM
# =============================================================================

@dataclass
class TestnetCircuitBreaker:
    """Disjuntor de segurança operacional para pausar envio de ordens na Testnet."""

    is_tripped: bool = False
    trip_reason: str = ""
    tripped_at: str = ""
    consecutive_errors: int = 0
    consecutive_auth_failures: int = 0
    unreconciled_unknown_count: int = 0
    orphan_orders_count: int = 0
    max_consecutive_errors: int = 5
    max_auth_failures: int = 3

    def trip(self, reason: str) -> None:
        """Dispara o disjuntor impedindo imediatamente novas ordens."""
        self.is_tripped = True
        self.trip_reason = reason
        self.tripped_at = datetime.now(timezone.utc).isoformat()
        logger.error("CIRCUIT BREAKER DISPARADO: %s. STOP_NEW_ORDERS = TRUE.", reason)

    def record_success(self) -> None:
        """Registra ciclo com sucesso e zera contador de erros consecutivos."""
        self.consecutive_errors = 0
        self.consecutive_auth_failures = 0

    def record_error(self, reason: str, is_auth: bool = False) -> None:
        """Registra erro operacional e dispara se exceder limites de tolerância."""
        self.consecutive_errors += 1
        if is_auth:
            self.consecutive_auth_failures += 1

        if self.consecutive_auth_failures >= self.max_auth_failures:
            self.trip(f"Falhas repetidas de autenticação ({self.consecutive_auth_failures}): {reason}")
        elif self.consecutive_errors >= self.max_consecutive_errors:
            self.trip(f"Número excessivo de erros consecutivos ({self.consecutive_errors}): {reason}")

    def record_unknown_order(self, client_order_id: str) -> None:
        """Ordem em estado UNKNOWN dispara o disjuntor imediatamente."""
        self.unreconciled_unknown_count += 1
        self.trip(f"Ordem UNKNOWN detectada sem confirmação: {client_order_id}")

    def record_orphan_order(self, order_id: str) -> None:
        """Ordem órfã na exchange dispara o disjuntor imediatamente."""
        self.orphan_orders_count += 1
        self.trip(f"Ordem órfã detectada na exchange: {order_id}")

    def record_balance_divergence(self, details: str) -> None:
        """Divergência crítica de saldo dispara o disjuntor."""
        self.trip(f"Divergência crítica de saldo: {details}")

    def reset(self) -> None:
        """Reinicia o disjuntor após intervenção explícita do operador."""
        self.is_tripped = False
        self.trip_reason = ""
        self.tripped_at = ""
        self.consecutive_errors = 0
        self.consecutive_auth_failures = 0
        self.unreconciled_unknown_count = 0
        logger.info("Circuit breaker reiniciado pelo operador. STOP_NEW_ORDERS = FALSE.")

    @property
    def unknown_orders_count(self) -> int:
        return self.unreconciled_unknown_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_tripped": self.is_tripped,
            "trip_reason": self.trip_reason,
            "tripped_at": self.tripped_at,
            "consecutive_errors": self.consecutive_errors,
            "consecutive_auth_failures": self.consecutive_auth_failures,
            "unreconciled_unknown_count": self.unreconciled_unknown_count,
            "orphan_orders_count": self.orphan_orders_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TestnetCircuitBreaker:
        return cls(
            is_tripped=bool(data.get("is_tripped", False)),
            trip_reason=str(data.get("trip_reason", "")),
            tripped_at=str(data.get("tripped_at", "")),
            consecutive_errors=int(data.get("consecutive_errors", 0)),
            consecutive_auth_failures=int(data.get("consecutive_auth_failures", 0)),
            unreconciled_unknown_count=int(data.get("unreconciled_unknown_count", 0)),
            orphan_orders_count=int(data.get("orphan_orders_count", 0)),
        )


# =============================================================================
# MODELOS DE MÉTRICAS OPERACIONAIS E FINANCEIRAS
# =============================================================================

@dataclass
class TestnetOperationalMetrics:
    """Métricas de confiabilidade e integridade operacional do Soak."""

    uptime_seconds: float = 0.0
    start_time: str = ""
    last_successful_cycle: str | None = None
    total_cycles: int = 0
    successful_cycles: int = 0
    failed_cycles: int = 0
    unhandled_exceptions: int = 0
    api_errors: int = 0
    timeouts: int = 0
    reconciliations: int = 0
    unknown_orders: int = 0
    orphan_orders: int = 0
    duplicate_blocks: int = 0
    orders_created: int = 0
    orders_filled: int = 0
    orders_canceled: int = 0
    orders_rejected: int = 0
    partial_fills: int = 0


@dataclass
class TestnetFinancialMetrics:
    """Métricas financeiras calculadas sobre o capital normalizado da estratégia."""

    testnet_strategy_capital: Decimal = DEFAULT_STRATEGY_CAPITAL
    starting_equity: Decimal = DEFAULT_STRATEGY_CAPITAL
    current_equity: Decimal = DEFAULT_STRATEGY_CAPITAL
    cash_balance: Decimal = DEFAULT_STRATEGY_CAPITAL
    btc_position: Decimal = Decimal("0.00000000")
    position_cost_basis: Decimal = Decimal("0.00")
    realized_pnl: Decimal = Decimal("0.00")
    unrealized_pnl: Decimal = Decimal("0.00")
    net_pnl: Decimal = Decimal("0.00")
    fees: Decimal = Decimal("0.00")
    exchange_reported_fees: Decimal = Decimal("0.00")
    estimated_fees: Decimal = Decimal("0.00")
    estimated_slippage: Decimal = Decimal("0.00")
    estimated_slippage_bps: Decimal = Decimal("0.00")
    gross_return_pct: float = 0.0
    net_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    win_rate_pct: float = 0.0
    loss_rate_pct: float = 0.0
    profit_factor: float = 0.0
    average_win: Decimal | None = None
    average_loss: Decimal | None = None
    expectancy: Decimal | None = None
    total_trades: int = 0
    closed_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    peak_equity: Decimal = DEFAULT_STRATEGY_CAPITAL
    trade_sample_size: int = 0
    observation_period_seconds: float = 0.0
    first_trade_at: str | None = None
    last_trade_at: str | None = None


@dataclass(frozen=True)
class TestnetPosition:
    """Posição Spot LONG simulada sobre o capital normalizado."""

    side: str = "NONE"  # "LONG" ou "NONE"
    quantity: Decimal = Decimal("0.00000000")
    cost_basis: Decimal = Decimal("0.00")
    entry_price: Decimal = Decimal("0.00")
    entry_timestamp: str = ""


@dataclass(frozen=True)
class TestnetTradeRecord:
    """Registro de operação executada na Testnet com semântica inequívoca."""

    client_order_id: str
    exchange_order_id: str | None
    timestamp: str
    symbol: str
    side: str
    order_type: str
    requested_quantity: Decimal
    executed_quantity: Decimal
    limit_price: Decimal | None = None
    average_fill_price: Decimal | None = None
    notional: Decimal = Decimal("0.00")
    fee: Decimal = Decimal("0.00")
    fee_asset: str | None = None
    realized_pnl: Decimal | None = None
    exit_reason: str | None = None
    reference_price: Decimal | None = None
    exchange_reported_fee: Decimal = Decimal("0.00")
    estimated_fee: Decimal = Decimal("0.00")
    fee_source: str = "EXCHANGE"
    estimated_slippage_usdt: Decimal = Decimal("0.00")
    estimated_slippage_bps: Decimal = Decimal("0.00")


# =============================================================================
# PERSISTÊNCIA SQLITE PARA TESTNET SOAK
# =============================================================================

class TestnetSoakStorage:
    """Armazenamento persistente SQLite para estado operacional, métricas e trades do Soak."""

    def __init__(self, db_path: str | Path = "data/finbot_testnet_soak.sqlite3") -> None:
        self.db_path = str(db_path)
        self._memory_conn: sqlite3.Connection | None = None
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if self.db_path == ":memory:":
            if self._memory_conn is None:
                self._memory_conn = sqlite3.connect(":memory:")
                self._memory_conn.row_factory = sqlite3.Row
            return self._memory_conn
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        conn = self._get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS soak_state (
                        key TEXT PRIMARY KEY,
                        value TEXT,
                        updated_at TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS soak_metrics (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        uptime_seconds REAL,
                        total_cycles INTEGER,
                        successful_cycles INTEGER,
                        failed_cycles INTEGER,
                        api_errors INTEGER,
                        unknown_orders INTEGER,
                        orphan_orders INTEGER,
                        orders_filled INTEGER,
                        starting_equity TEXT,
                        current_equity TEXT,
                        net_pnl TEXT,
                        net_return_pct REAL,
                        max_drawdown_pct REAL,
                        metrics_json TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS soak_trades (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        client_order_id TEXT UNIQUE NOT NULL,
                        exchange_order_id TEXT,
                        timestamp TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        side TEXT NOT NULL,
                        order_type TEXT NOT NULL,
                        requested_quantity TEXT NOT NULL,
                        executed_quantity TEXT NOT NULL,
                        limit_price TEXT,
                        average_fill_price TEXT,
                        notional TEXT NOT NULL,
                        fee TEXT,
                        fee_asset TEXT,
                        realized_pnl TEXT,
                        exit_reason TEXT,
                        reference_price TEXT,
                        exchange_reported_fee TEXT,
                        estimated_fee TEXT,
                        fee_source TEXT,
                        estimated_slippage_usdt TEXT,
                        estimated_slippage_bps TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS soak_position (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        side TEXT NOT NULL,
                        quantity TEXT NOT NULL,
                        cost_basis TEXT NOT NULL,
                        entry_price TEXT NOT NULL,
                        entry_timestamp TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                self._migrate_db(conn)
        finally:
            if self.db_path != ":memory:":
                conn.close()

    def _migrate_db(self, conn: sqlite3.Connection) -> None:
        """Aplica migrações seguras de colunas em bases existentes (preserva S1)."""
        cursor = conn.execute("PRAGMA table_info(soak_trades)")
        cols = {row["name"] for row in cursor.fetchall()}
        new_cols = [
            ("reference_price", "TEXT"),
            ("exchange_reported_fee", "TEXT"),
            ("estimated_fee", "TEXT"),
            ("fee_source", "TEXT"),
            ("estimated_slippage_usdt", "TEXT"),
            ("estimated_slippage_bps", "TEXT"),
        ]
        for col_name, col_type in new_cols:
            if col_name not in cols:
                conn.execute(f"ALTER TABLE soak_trades ADD COLUMN {col_name} {col_type}")

    def close(self) -> None:
        """Fecha a conexão com o banco se mantida em memória."""
        if self._memory_conn is not None:
            self._memory_conn.close()
            self._memory_conn = None

    def save_state(self, key: str, value: Any) -> None:
        conn = self._get_connection()
        try:
            val_str = json.dumps(value) if not isinstance(value, str) else value
            now_iso = datetime.now(timezone.utc).isoformat()
            with conn:
                conn.execute(
                    """
                    INSERT INTO soak_state (key, value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                    """,
                    (key, val_str, now_iso),
                )
        finally:
            if self.db_path != ":memory:":
                conn.close()

    def get_state(self, key: str, default: Any = None) -> Any:
        conn = self._get_connection()
        try:
            cursor = conn.execute("SELECT value FROM soak_state WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row is None:
                return default
            val_str = row["value"]
            try:
                return json.loads(val_str)
            except Exception:
                return val_str
        finally:
            if self.db_path != ":memory:":
                conn.close()

    def save_position(self, pos: TestnetPosition) -> None:
        conn = self._get_connection()
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            with conn:
                conn.execute(
                    """
                    INSERT INTO soak_position (id, side, quantity, cost_basis, entry_price, entry_timestamp, updated_at)
                    VALUES (1, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        side = excluded.side,
                        quantity = excluded.quantity,
                        cost_basis = excluded.cost_basis,
                        entry_price = excluded.entry_price,
                        entry_timestamp = excluded.entry_timestamp,
                        updated_at = excluded.updated_at
                    """,
                    (
                        pos.side,
                        str(pos.quantity),
                        str(pos.cost_basis),
                        str(pos.entry_price),
                        pos.entry_timestamp,
                        now_iso,
                    ),
                )
        finally:
            if self.db_path != ":memory:":
                conn.close()

    def get_position(self) -> TestnetPosition:
        conn = self._get_connection()
        try:
            cursor = conn.execute("SELECT * FROM soak_position WHERE id = 1")
            row = cursor.fetchone()
            if row is None:
                return TestnetPosition()
            return TestnetPosition(
                side=row["side"],
                quantity=Decimal(row["quantity"]),
                cost_basis=Decimal(row["cost_basis"]),
                entry_price=Decimal(row["entry_price"]),
                entry_timestamp=row["entry_timestamp"],
            )
        finally:
            if self.db_path != ":memory:":
                conn.close()

    def record_trade(self, trade: TestnetTradeRecord) -> None:
        conn = self._get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO soak_trades (
                        client_order_id, exchange_order_id, timestamp, symbol, side,
                        order_type, requested_quantity, executed_quantity, limit_price,
                        average_fill_price, notional, fee, fee_asset, realized_pnl, exit_reason,
                        reference_price, exchange_reported_fee, estimated_fee, fee_source,
                        estimated_slippage_usdt, estimated_slippage_bps
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(client_order_id) DO UPDATE SET
                        executed_quantity = excluded.executed_quantity,
                        average_fill_price = excluded.average_fill_price,
                        realized_pnl = excluded.realized_pnl,
                        fee = excluded.fee,
                        reference_price = excluded.reference_price,
                        exchange_reported_fee = excluded.exchange_reported_fee,
                        estimated_fee = excluded.estimated_fee,
                        fee_source = excluded.fee_source,
                        estimated_slippage_usdt = excluded.estimated_slippage_usdt,
                        estimated_slippage_bps = excluded.estimated_slippage_bps
                    """,
                    (
                        trade.client_order_id,
                        trade.exchange_order_id,
                        trade.timestamp,
                        trade.symbol,
                        trade.side,
                        trade.order_type,
                        str(trade.requested_quantity),
                        str(trade.executed_quantity),
                        str(trade.limit_price) if trade.limit_price is not None else None,
                        str(trade.average_fill_price) if trade.average_fill_price is not None else None,
                        str(trade.notional),
                        str(trade.fee),
                        trade.fee_asset,
                        str(trade.realized_pnl) if trade.realized_pnl is not None else None,
                        trade.exit_reason,
                        str(trade.reference_price) if trade.reference_price is not None else None,
                        str(trade.exchange_reported_fee) if trade.exchange_reported_fee is not None else "0.00",
                        str(trade.estimated_fee) if trade.estimated_fee is not None else "0.00",
                        trade.fee_source,
                        str(trade.estimated_slippage_usdt) if trade.estimated_slippage_usdt is not None else "0.00",
                        str(trade.estimated_slippage_bps) if trade.estimated_slippage_bps is not None else "0.00",
                    ),
                )
        finally:
            if self.db_path != ":memory:":
                conn.close()

    def list_trades(self) -> list[TestnetTradeRecord]:
        conn = self._get_connection()
        try:
            def _parse_dec(val: Any, default: Decimal | None = None) -> Decimal | None:
                if val is None or val == "" or val == "None":
                    return default
                try:
                    return Decimal(str(val))
                except Exception:
                    return default

            cursor = conn.execute("SELECT * FROM soak_trades ORDER BY id ASC")
            trades: list[TestnetTradeRecord] = []
            for r in cursor.fetchall():
                keys = r.keys()
                fee_val = _parse_dec(r["fee"], Decimal("0.00")) or Decimal("0.00")
                trades.append(
                    TestnetTradeRecord(
                        client_order_id=r["client_order_id"],
                        exchange_order_id=r["exchange_order_id"],
                        timestamp=r["timestamp"],
                        symbol=r["symbol"],
                        side=r["side"],
                        order_type=r["order_type"],
                        requested_quantity=_parse_dec(r["requested_quantity"], Decimal("0.00")) or Decimal("0.00"),
                        executed_quantity=_parse_dec(r["executed_quantity"], Decimal("0.00")) or Decimal("0.00"),
                        limit_price=_parse_dec(r["limit_price"]),
                        average_fill_price=_parse_dec(r["average_fill_price"]),
                        notional=_parse_dec(r["notional"], Decimal("0.00")) or Decimal("0.00"),
                        fee=fee_val,
                        fee_asset=r["fee_asset"],
                        realized_pnl=_parse_dec(r["realized_pnl"]),
                        exit_reason=r["exit_reason"],
                        reference_price=_parse_dec(r["reference_price"]) if "reference_price" in keys else None,
                        exchange_reported_fee=_parse_dec(r["exchange_reported_fee"], Decimal("0.00")) if "exchange_reported_fee" in keys else Decimal("0.00"),
                        estimated_fee=_parse_dec(r["estimated_fee"], Decimal("0.00")) if "estimated_fee" in keys else Decimal("0.00"),
                        fee_source=r["fee_source"] if "fee_source" in keys and r["fee_source"] is not None else ("EXCHANGE" if fee_val > Decimal("0") else "ZERO"),
                        estimated_slippage_usdt=_parse_dec(r["estimated_slippage_usdt"], Decimal("0.00")) if "estimated_slippage_usdt" in keys else Decimal("0.00"),
                        estimated_slippage_bps=_parse_dec(r["estimated_slippage_bps"], Decimal("0.00")) if "estimated_slippage_bps" in keys else Decimal("0.00"),
                    )
                )
            return trades
        finally:
            if self.db_path != ":memory:":
                conn.close()

    def save_metrics_snapshot(
        self,
        op_metrics: TestnetOperationalMetrics,
        fin_metrics: TestnetFinancialMetrics,
    ) -> None:
        conn = self._get_connection()
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            metrics_payload = {
                "operational": {
                    "uptime_seconds": op_metrics.uptime_seconds,
                    "total_cycles": op_metrics.total_cycles,
                    "successful_cycles": op_metrics.successful_cycles,
                    "failed_cycles": op_metrics.failed_cycles,
                    "api_errors": op_metrics.api_errors,
                    "timeouts": op_metrics.timeouts,
                    "reconciliations": op_metrics.reconciliations,
                    "unknown_orders": op_metrics.unknown_orders,
                    "orphan_orders": op_metrics.orphan_orders,
                    "duplicate_blocks": op_metrics.duplicate_blocks,
                    "orders_created": op_metrics.orders_created,
                    "orders_filled": op_metrics.orders_filled,
                    "orders_canceled": op_metrics.orders_canceled,
                    "orders_rejected": op_metrics.orders_rejected,
                    "partial_fills": op_metrics.partial_fills,
                },
                "financial": {
                    "strategy_capital": str(fin_metrics.testnet_strategy_capital),
                    "starting_equity": str(fin_metrics.starting_equity),
                    "current_equity": str(fin_metrics.current_equity),
                    "cash_balance": str(fin_metrics.cash_balance),
                    "realized_pnl": str(fin_metrics.realized_pnl),
                    "unrealized_pnl": str(fin_metrics.unrealized_pnl),
                    "net_pnl": str(fin_metrics.net_pnl),
                    "fees": str(fin_metrics.fees),
                    "exchange_reported_fees": str(fin_metrics.exchange_reported_fees),
                    "estimated_fees": str(fin_metrics.estimated_fees),
                    "estimated_slippage": str(fin_metrics.estimated_slippage),
                    "estimated_slippage_bps": str(fin_metrics.estimated_slippage_bps),
                    "gross_return_pct": fin_metrics.gross_return_pct,
                    "net_return_pct": fin_metrics.net_return_pct,
                    "max_drawdown_pct": fin_metrics.max_drawdown_pct,
                    "win_rate_pct": fin_metrics.win_rate_pct,
                    "profit_factor": fin_metrics.profit_factor,
                    "average_win": str(fin_metrics.average_win) if fin_metrics.average_win is not None else None,
                    "average_loss": str(fin_metrics.average_loss) if fin_metrics.average_loss is not None else None,
                    "expectancy": str(fin_metrics.expectancy) if fin_metrics.expectancy is not None else None,
                    "total_trades": fin_metrics.total_trades,
                    "closed_trades": fin_metrics.closed_trades,
                    "first_trade_at": fin_metrics.first_trade_at,
                    "last_trade_at": fin_metrics.last_trade_at,
                },
            }
            with conn:
                conn.execute(
                    """
                    INSERT INTO soak_metrics (
                        timestamp, uptime_seconds, total_cycles, successful_cycles,
                        failed_cycles, api_errors, unknown_orders, orphan_orders,
                        orders_filled, starting_equity, current_equity, net_pnl,
                        net_return_pct, max_drawdown_pct, metrics_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        now_iso,
                        op_metrics.uptime_seconds,
                        op_metrics.total_cycles,
                        op_metrics.successful_cycles,
                        op_metrics.failed_cycles,
                        op_metrics.api_errors,
                        op_metrics.unknown_orders,
                        op_metrics.orphan_orders,
                        op_metrics.orders_filled,
                        str(fin_metrics.starting_equity),
                        str(fin_metrics.current_equity),
                        str(fin_metrics.net_pnl),
                        fin_metrics.net_return_pct,
                        fin_metrics.max_drawdown_pct,
                        json.dumps(metrics_payload),
                    ),
                )
        finally:
            if self.db_path != ":memory:":
                conn.close()

    def get_latest_metrics(self) -> dict[str, Any] | None:
        conn = self._get_connection()
        try:
            cursor = conn.execute("SELECT * FROM soak_metrics ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            if row is None:
                return None
            return {
                "timestamp": row["timestamp"],
                "uptime_seconds": row["uptime_seconds"],
                "total_cycles": row["total_cycles"],
                "successful_cycles": row["successful_cycles"],
                "failed_cycles": row["failed_cycles"],
                "api_errors": row["api_errors"],
                "unknown_orders": row["unknown_orders"],
                "orphan_orders": row["orphan_orders"],
                "orders_filled": row["orders_filled"],
                "starting_equity": row["starting_equity"],
                "current_equity": row["current_equity"],
                "net_pnl": row["net_pnl"],
                "net_return_pct": row["net_return_pct"],
                "max_drawdown_pct": row["max_drawdown_pct"],
                "details": json.loads(row["metrics_json"]) if row["metrics_json"] else {},
            }
        finally:
            if self.db_path != ":memory:":
                conn.close()


# =============================================================================
# SENTRIES DEFENSIVOS FAIL-CLOSED
# =============================================================================

def verify_testnet_soak_sentries(
    config: Config,
    adapter: ExchangeOrderAdapter,
    credential_provider: WindowsCredentialProvider | None = None,
) -> None:
    """Valida barreiras incondicionais antes de qualquer ciclo do Testnet Soak."""
    if config.binance_environment != BinanceEnvironment.SPOT_TESTNET:
        raise TestnetSoakSentryError(
            f"Ambiente deve ser estritamente SPOT_TESTNET. Atual: {config.binance_environment}"
        )

    if not config.testnet_execution_enabled:
        raise TestnetSoakSentryError(
            "Execução na Testnet não está habilitada (testnet_execution_enabled == False)."
        )

    if config.real_order_submission_enabled:
        raise TestnetSoakSentryError(
            "VIOLAÇÃO CRÍTICA: real_order_submission_enabled está ativada. Produção proibida!"
        )

    if isinstance(adapter, FakeExchangeOrderAdapter):
        if adapter.environment != BinanceEnvironment.SPOT_TESTNET:
            raise TestnetSoakSentryError("FakeAdapter não está configurado para SPOT_TESTNET.")
    elif isinstance(adapter, BinanceSpotTestnetOrderAdapter):
        if adapter.environment != BinanceEnvironment.SPOT_TESTNET:
            raise TestnetSoakSentryError("BinanceSpotTestnetOrderAdapter não está em SPOT_TESTNET.")
    else:
        raise TestnetSoakSentryError(
            f"Tipo de adapter não autorizado para Testnet: {type(adapter).__name__}"
        )

    raw_urls = getattr(adapter, "urls", None)
    if isinstance(raw_urls, dict):
        api_urls = raw_urls.get("api", {})
        urls_to_check: list[str] = []
        if isinstance(api_urls, dict):
            urls_to_check.extend([str(v) for v in api_urls.values() if isinstance(v, str)])
        elif isinstance(api_urls, str):
            urls_to_check.append(api_urls)

        for u in urls_to_check:
            if PRODUCTION_DOMAIN in u:
                raise TestnetSoakSentryError(f"VIOLAÇÃO DE ISOLAMENTO: URL de Produção detectada ({u})!")
            if TESTNET_DOMAIN not in u:
                raise TestnetSoakSentryError(f"URL não pertence ao domínio da Testnet: {u}")

    if credential_provider is not None:
        target = getattr(credential_provider, "target_name", "")
        if TARGET_NAME_PRODUCTION in target:
            raise TestnetSoakSentryError(f"VIOLAÇÃO DE CREDENCIAIS: Target de Produção detectado ({target})!")
        if TARGET_NAME_TESTNET not in target:
            raise TestnetSoakSentryError(f"Target de credenciais deve ser {TARGET_NAME_TESTNET}.")


# =============================================================================
# STATUS REAL DO RUNNER & HEARTBEAT (OBSERVABILIDADE FIDEDIGNA)
# =============================================================================

def determine_runner_status(
    storage: TestnetSoakStorage,
    circuit_breaker: TestnetCircuitBreaker | None = None,
    heartbeat_timeout_seconds: float = 180.0,
    now: datetime | None = None,
) -> str:
    """Determina o status operacional fidedigno do runner do Soak.

    Estados:
    - CIRCUIT_BREAKER_TRIPPED: Disjuntor de segurança armado (novas ordens travadas).
    - RUNNING: Runner em execução ativa com heartbeat recente (dentro do timeout).
    - STOPPED: Encerramento explícito (Ctrl+C / normal) ou heartbeat expirado/stale.
    - READY/IDLE: Antes de qualquer execução ou estado ocioso sem processos ativos.
    """
    if circuit_breaker and circuit_breaker.is_tripped:
        return "CIRCUIT_BREAKER_TRIPPED"

    latest = storage.get_latest_metrics()
    runner_state = storage.get_state("runner_status", None)
    last_hb_str = storage.get_state("last_heartbeat", None) or storage.get_state("last_cycle_at", None)

    if latest is None and runner_state is None and last_hb_str is None:
        return "READY/IDLE"

    if runner_state == "STOPPED":
        return "STOPPED"

    if now is None:
        now = datetime.now(timezone.utc)

    # Se runner_state estiver marcado como RUNNING ou se houver heartbeat registrado
    if last_hb_str:
        try:
            hb_dt = datetime.fromisoformat(last_hb_str)
            if hb_dt.tzinfo is None:
                hb_dt = hb_dt.replace(tzinfo=timezone.utc)
            elapsed = (now - hb_dt).total_seconds()
            if runner_state == "RUNNING" and elapsed <= heartbeat_timeout_seconds:
                return "RUNNING"
            else:
                # Heartbeat expirado ou ausência de status explícito RUNNING fresco -> STOPPED
                return "STOPPED"
        except Exception:
            return "STOPPED"

    return "READY/IDLE"


# =============================================================================
# RESTART SEGURO (RECONCILIAÇÃO E RECONSTRUÇÃO PRÉVIA A QUALQUER ORDEM)
# =============================================================================

def reconcile_pre_cycle_state(
    config: Config,
    storage: TestnetSoakStorage,
    order_storage: LiveOrderStorage,
    adapter: ExchangeOrderAdapter,
    circuit_breaker: TestnetCircuitBreaker,
    now_iso: str | None = None,
) -> tuple[TestnetPosition, bool, int]:
    """Executa a reconciliação prévia obrigatória antes de qualquer decisão da estratégia.

    Garante:
    1. Carrega checkpoint anterior;
    2. Reconcilia todas as ordens não terminais;
    3. Reconstrói a posição local a partir dos trades confirmados;
    4. Compara com os saldos reais da Testnet (se disponíveis no adapter);
    5. Dispara circuit breaker se houver ordem UNKNOWN não resolvida ou divergência de saldo;
    6. Retorna (posição, can_proceed, reconciliations_count).
    Nenhum CREATE automático é permitido antes desta validação.
    """
    if now_iso is None:
        now_iso = datetime.now(timezone.utc).isoformat()

    # 1. Carrega ordens pendentes/não terminais
    unreconciled = order_storage.get_unreconciled_orders()
    non_terminal_statuses = {
        OrderStatus.PENDING_SUBMISSION,
        OrderStatus.SUBMITTED,
        OrderStatus.ACKNOWLEDGED,
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.CANCEL_PENDING,
        OrderStatus.UNKNOWN,
    }

    candidates_to_reconcile = list(unreconciled)
    reconciliations_count = 0

    # 2. Reconcilia ordens não terminais com a exchange
    for unrec in candidates_to_reconcile:
        cid = unrec["client_order_id"]
        reconciliations_count += 1
        try:
            fetched = adapter.fetch_order(config.symbol, unrec.get("exchange_order_id"), cid)
            if fetched is not None:
                order_storage.update_order_status(
                    client_order_id=cid,
                    status=fetched.status,
                    updated_at=now_iso,
                    exchange_order_id=fetched.exchange_order_id,
                    executed_quantity=fetched.executed_quantity,
                    cumulative_quote_quantity=fetched.cumulative_quote_quantity,
                    average_price=fetched.average_price,
                )
                logger.info("Ordem pendente reconciliada no restart: %s -> %s", cid, fetched.status.value)

                # Se preencheu, assegura registro no histórico de trades do soak
                if fetched.status == OrderStatus.FILLED:
                    existing_trades = {t.client_order_id for t in storage.list_trades()}
                    if cid not in existing_trades:
                        rep_fee = fetched.fee or Decimal("0.00")
                        trade_rec = TestnetTradeRecord(
                            client_order_id=fetched.client_order_id,
                            exchange_order_id=fetched.exchange_order_id,
                            timestamp=now_iso,
                            symbol=fetched.symbol,
                            side=fetched.side,
                            order_type=fetched.order_type,
                            requested_quantity=fetched.requested_quantity,
                            executed_quantity=fetched.executed_quantity,
                            limit_price=fetched.limit_price,
                            average_fill_price=fetched.average_fill_price,
                            notional=fetched.cumulative_quote_quantity,
                            fee=rep_fee,
                            fee_asset=fetched.fee_asset,
                            exchange_reported_fee=rep_fee,
                            estimated_fee=Decimal("0.00"),
                            fee_source="EXCHANGE" if rep_fee > Decimal("0.00") else "ZERO",
                        )
                        storage.record_trade(trade_rec)
            else:
                circuit_breaker.record_unknown_order(cid)
                logger.warning("Ordem não localizada na exchange (UNKNOWN): %s", cid)
        except Exception as exc:
            circuit_breaker.record_unknown_order(cid)
            logger.error("Erro ao reconciliar ordem no restart: %s (%s)", cid, exc)

    # 3. Reconstrói a posição local a partir do histórico de trades
    trades = storage.list_trades()
    _, reconstructed_pos = recalculate_financial_metrics(
        trades=trades,
        current_price=Decimal("60000.00"),  # Preço base para reconstrução de inventário
        strategy_capital=Decimal(str(config.testnet_strategy_capital)),
    )
    storage.save_position(reconstructed_pos)

    # 4. Compara com saldos da exchange (se adapter suportar get_balances)
    if hasattr(adapter, "get_balances"):
        try:
            balances = adapter.get_balances()
            if isinstance(balances, dict):
                btc_data = balances.get("BTC")
                if isinstance(btc_data, dict):
                    btc_free = Decimal(str(btc_data.get("free", "0.0")))
                elif btc_data is not None:
                    btc_free = Decimal(str(getattr(btc_data, "free", 0.0)))
                else:
                    btc_free = Decimal("0.0")

                # Se posição local diz LONG com quantidade Q, verificar se há BTC livre compatível
                if reconstructed_pos.side == "LONG" and reconstructed_pos.quantity > Decimal("0"):
                    if btc_free < (reconstructed_pos.quantity * Decimal("0.99")):
                        circuit_breaker.record_balance_divergence(
                            f"Posição local LONG ({reconstructed_pos.quantity} BTC), mas saldo livre na Testnet é {btc_free} BTC"
                        )
        except Exception as exc:
            logger.warning("Não foi possível conferir saldos da Testnet no restart: %s", exc)

    can_proceed = not circuit_breaker.is_tripped
    return reconstructed_pos, can_proceed, reconciliations_count


# =============================================================================
# CÁLCULOS FINANCEIROS E DE MÉTRICAS (PURA / DETERMINÍSTICA)
# =============================================================================

def recalculate_financial_metrics(
    trades: list[TestnetTradeRecord],
    current_price: Decimal,
    strategy_capital: Decimal = DEFAULT_STRATEGY_CAPITAL,
    observation_period_seconds: float = 0.0,
    default_fee_rate: Decimal = Decimal("0.0010"),
) -> tuple[TestnetFinancialMetrics, TestnetPosition]:
    """Recalcula o estado financeiro da estratégia a partir dos trades reais executados na Testnet.

    Garante:
    - executed_quantity == 0 NÃO afeta PnL nem preço médio (ordem cancelada sem fill não afeta nada).
    - Preserva o capital normalizado (strategy_capital) independente do saldo massivo da exchange.
    - Contabilização segregada de taxas: EXCHANGE_REPORTED_FEES e ESTIMATED_FEES.
    - Contabilização de slippage por fill (BUY: fill - ref; SELL: ref - fill) em USDT e bps.
    - Slippage NÃO é duplicado no NET_PNL: fill_price já determina os fluxos reais de caixa.
    - Posições abertas (open trades) não entram na contagem de trades fechados (closed_trades).
    - Preenchimentos parciais são contabilizados pela quantidade real executada e proporção de custo.
    - PnL não realizado (unrealized_pnl) permanece rigorosamente separado de PnL realizado.
    """
    cash = strategy_capital
    pos_qty = Decimal("0.00000000")
    pos_cost = Decimal("0.00")
    entry_px = Decimal("0.00")
    entry_ts = ""

    realized_pnl = Decimal("0.00")
    total_effective_fees = Decimal("0.00")
    total_reported_fees = Decimal("0.00")
    total_estimated_fees = Decimal("0.00")
    total_slippage_usdt = Decimal("0.00")
    total_slippage_bps_weighted = Decimal("0.00")
    total_slippage_notional = Decimal("0.00")

    closed_trades = 0
    winning_trades = 0
    losing_trades = 0
    sum_wins = Decimal("0.00")
    sum_losses = Decimal("0.00")

    first_trade_at: str | None = None
    last_trade_at: str | None = None

    peak_equity = strategy_capital
    max_drawdown = 0.0

    for t in trades:
        # Se ordem não preencheu (exec_qty == 0), ignora para efeitos financeiros
        if t.executed_quantity == Decimal("0"):
            continue

        fill_px = t.average_fill_price
        if fill_px is None or fill_px <= Decimal("0"):
            continue

        if first_trade_at is None:
            first_trade_at = t.timestamp
        last_trade_at = t.timestamp

        trade_notional = t.executed_quantity * fill_px

        # 1. Contabilização segregada de Fees
        rep_fee = t.exchange_reported_fee
        est_fee = t.estimated_fee
        if rep_fee > Decimal("0.00"):
            effective_fee = rep_fee
            total_reported_fees += rep_fee
        elif est_fee > Decimal("0.00"):
            effective_fee = est_fee
            total_estimated_fees += est_fee
        elif t.fee > Decimal("0.00"):
            effective_fee = t.fee
            total_reported_fees += t.fee
        else:
            effective_fee = Decimal("0.00")

        total_effective_fees += effective_fee

        # 2. Contabilização de Slippage
        slip_usdt = t.estimated_slippage_usdt
        slip_bps = t.estimated_slippage_bps

        if slip_usdt == Decimal("0.00") and t.reference_price is not None and t.reference_price > Decimal("0"):
            ref_px = t.reference_price
            if t.side == "BUY":
                slip_usdt = (fill_px - ref_px) * t.executed_quantity
                slip_bps = ((fill_px - ref_px) / ref_px) * Decimal("10000")
            elif t.side == "SELL":
                slip_usdt = (ref_px - fill_px) * t.executed_quantity
                slip_bps = ((ref_px - fill_px) / ref_px) * Decimal("10000")
        elif slip_usdt == Decimal("0.00") and t.limit_price is not None and t.limit_price > Decimal("0"):
            lim_px = t.limit_price
            if t.side == "BUY":
                slip_usdt = (fill_px - lim_px) * t.executed_quantity
                slip_bps = ((fill_px - lim_px) / lim_px) * Decimal("10000")
            elif t.side == "SELL":
                slip_usdt = (lim_px - fill_px) * t.executed_quantity
                slip_bps = ((lim_px - fill_px) / lim_px) * Decimal("10000")

        total_slippage_usdt += slip_usdt
        if trade_notional > Decimal("0"):
            total_slippage_notional += trade_notional
            total_slippage_bps_weighted += (slip_bps * trade_notional)

        # 3. Impacto Financeiro em Caixa e Posição (COM DEDUÇÃO DE TAXAS)
        # Nota metodológica: Slippage NÃO é deduzido novamente aqui porque o preço fill_px
        # já é o valor real da transação que define a saída/entrada do caixa.
        if t.side == "BUY":
            cost = (t.executed_quantity * fill_px) + effective_fee
            cash -= cost
            pos_qty += t.executed_quantity
            pos_cost += cost
            entry_px = fill_px
            entry_ts = t.timestamp

        elif t.side == "SELL":
            gross_proceeds = t.executed_quantity * fill_px
            net_proceeds = gross_proceeds - effective_fee
            cash += net_proceeds

            # PnL realizado do trade fechado
            if pos_cost > Decimal("0"):
                if pos_qty > Decimal("0") and t.executed_quantity < pos_qty:
                    portion_cost = (t.executed_quantity / pos_qty) * pos_cost
                    trade_pnl = net_proceeds - portion_cost
                    pos_cost -= portion_cost
                    pos_qty -= t.executed_quantity
                else:
                    trade_pnl = net_proceeds - pos_cost
                    pos_qty = Decimal("0.00000000")
                    pos_cost = Decimal("0.00")
                    entry_px = Decimal("0.00")
                    entry_ts = ""
            else:
                trade_pnl = net_proceeds
                pos_qty = Decimal("0.00000000")
                pos_cost = Decimal("0.00")
                entry_px = Decimal("0.00")
                entry_ts = ""

            realized_pnl += trade_pnl
            closed_trades += 1

            if trade_pnl > Decimal("0"):
                winning_trades += 1
                sum_wins += trade_pnl
            elif trade_pnl < Decimal("0"):
                losing_trades += 1
                sum_losses += abs(trade_pnl)

        # Tracking de drawdown ponto a ponto
        current_eq = cash + (pos_qty * fill_px)
        if current_eq > peak_equity:
            peak_equity = current_eq
        elif peak_equity > Decimal("0"):
            dd = float(((peak_equity - current_eq) / peak_equity) * Decimal("100"))
            if dd > max_drawdown:
                max_drawdown = dd

    # PnL não realizado da posição aberta atual (se houver)
    unrealized_pnl = Decimal("0.00")
    if pos_qty > Decimal("0") and current_price > Decimal("0"):
        current_val = pos_qty * current_price
        unrealized_pnl = current_val - pos_cost

    current_equity = cash + (pos_qty * current_price)
    if current_equity > peak_equity:
        peak_equity = current_equity
    elif peak_equity > Decimal("0"):
        dd = float(((peak_equity - current_equity) / peak_equity) * Decimal("100"))
        if dd > max_drawdown:
            max_drawdown = dd

    net_pnl = current_equity - strategy_capital
    net_return_pct = float((net_pnl / strategy_capital) * Decimal("100")) if strategy_capital > Decimal("0") else 0.0
    gross_return_pct = float(((net_pnl + total_effective_fees) / strategy_capital) * Decimal("100")) if strategy_capital > Decimal("0") else 0.0

    win_rate_pct = round((winning_trades / closed_trades) * 100.0, 2) if closed_trades > 0 else 0.0
    loss_rate_pct = round((losing_trades / closed_trades) * 100.0, 2) if closed_trades > 0 else 0.0

    profit_factor = float(sum_wins / sum_losses) if sum_losses > Decimal("0") else (float("inf") if sum_wins > Decimal("0") else 0.0)
    avg_win = (sum_wins / Decimal(str(winning_trades))) if winning_trades > 0 else None
    avg_loss = (sum_losses / Decimal(str(losing_trades))) if losing_trades > 0 else None

    expectancy = None
    if closed_trades > 0 and avg_win is not None:
        wr = Decimal(str(win_rate_pct / 100.0))
        lr = Decimal(str(loss_rate_pct / 100.0))
        loss_val = avg_loss or Decimal("0.00")
        expectancy = (wr * avg_win) - (lr * loss_val)

    avg_slippage_bps = (
        (total_slippage_bps_weighted / total_slippage_notional).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if total_slippage_notional > Decimal("0")
        else Decimal("0.00")
    )

    fin_metrics = TestnetFinancialMetrics(
        testnet_strategy_capital=strategy_capital,
        starting_equity=strategy_capital,
        current_equity=current_equity.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        cash_balance=cash.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        btc_position=pos_qty,
        position_cost_basis=pos_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        realized_pnl=realized_pnl.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        unrealized_pnl=unrealized_pnl.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        net_pnl=net_pnl.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        fees=total_effective_fees.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        exchange_reported_fees=total_reported_fees.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        estimated_fees=total_estimated_fees.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        estimated_slippage=total_slippage_usdt.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        estimated_slippage_bps=avg_slippage_bps,
        gross_return_pct=round(gross_return_pct, 4),
        net_return_pct=round(net_return_pct, 4),
        max_drawdown_pct=round(max_drawdown, 2),
        win_rate_pct=win_rate_pct,
        loss_rate_pct=loss_rate_pct,
        profit_factor=round(profit_factor, 2) if profit_factor != float("inf") else 999.99,
        average_win=avg_win.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if avg_win is not None else None,
        average_loss=avg_loss.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if avg_loss is not None else None,
        expectancy=expectancy.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if expectancy is not None else None,
        total_trades=len(trades),
        closed_trades=closed_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        peak_equity=peak_equity.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        trade_sample_size=closed_trades,
        observation_period_seconds=observation_period_seconds,
        first_trade_at=first_trade_at,
        last_trade_at=last_trade_at,
    )

    pos = TestnetPosition(
        side="LONG" if pos_qty > Decimal("0") else "NONE",
        quantity=pos_qty,
        cost_basis=pos_cost,
        entry_price=entry_px,
        entry_timestamp=entry_ts,
    )

    return fin_metrics, pos


# =============================================================================
# CICLO ONE-SHOT DO TESTNET SOAK
# =============================================================================

@dataclass
class TestnetSoakCycleResult:
    """Resultado da execução de um ciclo isolado do Testnet Soak."""

    timestamp: str
    cycle_status: str  # "SUCCESS", "HOLD", "BUY_EXECUTED", "SELL_EXECUTED", "BLOCKED_CIRCUIT_BREAKER", "ERROR"
    signal: Signal
    closed_candle_time: str
    closed_candle_timestamp: int
    executed_order: ExchangeOrderResult | None
    circuit_breaker_tripped: bool
    circuit_breaker_reason: str
    operational_metrics: TestnetOperationalMetrics
    financial_metrics: TestnetFinancialMetrics
    message: str = ""


def execute_testnet_soak_cycle(
    config: Config,
    storage: TestnetSoakStorage,
    order_storage: LiveOrderStorage,
    adapter: ExchangeOrderAdapter,
    circuit_breaker: TestnetCircuitBreaker,
    credential_provider: WindowsCredentialProvider | None = None,
    now_ms: int | None = None,
    ticker_override: float | None = None,
    candles_override: list[CandleData] | None = None,
) -> TestnetSoakCycleResult:
    """Executa um ciclo do Testnet Soak com validações rigorosas e tratamento de falhas."""
    if now_ms is None:
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    now_iso = datetime.now(timezone.utc).isoformat()

    # 1. Carrega métricas e estado prévios
    start_time_iso = storage.get_state("start_time", now_iso)
    total_cycles = int(storage.get_state("total_cycles", 0)) + 1
    successful_cycles = int(storage.get_state("successful_cycles", 0))
    failed_cycles = int(storage.get_state("failed_cycles", 0))
    api_errors = int(storage.get_state("api_errors", 0))
    timeouts = int(storage.get_state("timeouts", 0))
    reconciliations = int(storage.get_state("reconciliations", 0))
    unknown_orders = int(storage.get_state("unknown_orders", 0))
    orphan_orders = int(storage.get_state("orphan_orders", 0))
    duplicate_blocks = int(storage.get_state("duplicate_blocks", 0))
    orders_created = int(storage.get_state("orders_created", 0))
    orders_filled = int(storage.get_state("orders_filled", 0))
    orders_canceled = int(storage.get_state("orders_canceled", 0))
    orders_rejected = int(storage.get_state("orders_rejected", 0))
    partial_fills = int(storage.get_state("partial_fills", 0))

    try:
        start_dt = datetime.fromisoformat(start_time_iso)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        uptime_sec = max(0.0, (datetime.now(timezone.utc) - start_dt).total_seconds())
    except Exception:
        uptime_sec = 0.0

    # 2. Sentries Defensivos Pré-Execução
    try:
        verify_testnet_soak_sentries(config, adapter, credential_provider)
    except TestnetSoakSentryError as err:
        circuit_breaker.trip(f"Falha de sentry defensivo: {err}")
        storage.save_state("circuit_breaker", circuit_breaker.to_dict())
        failed_cycles += 1
        storage.save_state("total_cycles", total_cycles)
        storage.save_state("failed_cycles", failed_cycles)

        trades = storage.list_trades()
        fin_m, _ = recalculate_financial_metrics(trades, Decimal("60000.00"), Decimal(str(config.testnet_strategy_capital)), uptime_sec)
        op_m = TestnetOperationalMetrics(
            uptime_seconds=uptime_sec,
            start_time=start_time_iso,
            total_cycles=total_cycles,
            failed_cycles=failed_cycles,
            unknown_orders=unknown_orders,
            api_errors=api_errors + 1,
        )
        return TestnetSoakCycleResult(
            timestamp=now_iso,
            cycle_status="ERROR",
            signal=Signal.HOLD,
            closed_candle_time="",
            closed_candle_timestamp=0,
            executed_order=None,
            circuit_breaker_tripped=True,
            circuit_breaker_reason=str(err),
            operational_metrics=op_m,
            financial_metrics=fin_m,
            message=f"Sentry error: {err}",
        )

    # 3. RECONCILIAÇÃO PRÉVIA MANDATÓRIA APÓS RESTART / PRE-CYCLE
    # Reconcilia ordens não terminais, reconstrói inventário e compara com Testnet
    reconstructed_pos, can_proceed, pre_reconciliations = reconcile_pre_cycle_state(
        config=config,
        storage=storage,
        order_storage=order_storage,
        adapter=adapter,
        circuit_breaker=circuit_breaker,
        now_iso=now_iso,
    )
    reconciliations += pre_reconciliations

    if not can_proceed or circuit_breaker.is_tripped:
        trades = storage.list_trades()
        fin_m, _ = recalculate_financial_metrics(trades, Decimal("60000.00"), Decimal(str(config.testnet_strategy_capital)), uptime_sec)
        op_m = TestnetOperationalMetrics(
            uptime_seconds=uptime_sec,
            start_time=start_time_iso,
            total_cycles=total_cycles,
            failed_cycles=failed_cycles,
            api_errors=api_errors,
            unknown_orders=circuit_breaker.unknown_orders_count,
            reconciliations=reconciliations,
        )
        status_label = "BLOCKED_CIRCUIT_BREAKER" if circuit_breaker.is_tripped else "BLOCKED_PRE_CYCLE_RECONCILIATION"
        msg_label = (
            f"Novas ordens bloqueadas por Circuit Breaker: {circuit_breaker.trip_reason}"
            if circuit_breaker.is_tripped
            else f"Reconciliação prévia bloqueou ciclo: {circuit_breaker.trip_reason}"
        )
        return TestnetSoakCycleResult(
            timestamp=now_iso,
            cycle_status=status_label,
            signal=Signal.HOLD,
            closed_candle_time="",
            closed_candle_timestamp=0,
            executed_order=None,
            circuit_breaker_tripped=circuit_breaker.is_tripped,
            circuit_breaker_reason=circuit_breaker.trip_reason,
            operational_metrics=op_m,
            financial_metrics=fin_m,
            message=msg_label,
        )

    # 4. Obtenção de Market Data (público)
    try:
        if candles_override is not None and ticker_override is not None:
            raw_candles = candles_override
            last_price_float = ticker_override
        else:
            ex = create_exchange(config.exchange_id)
            try:
                tk = fetch_ticker(ex, config.symbol)
                last_price_float = float(tk.last)
                raw_candles = fetch_candles(
                    ex,
                    symbol=config.symbol,
                    timeframe=config.paper_timeframe,
                    limit=config.paper_candle_limit,
                )
            finally:
                close_exchange(ex)
    except Exception as exc:
        api_errors += 1
        failed_cycles += 1
        circuit_breaker.record_error(f"Erro ao obter dados de mercado: {exc}")
        storage.save_state("total_cycles", total_cycles)
        storage.save_state("failed_cycles", failed_cycles)
        storage.save_state("api_errors", api_errors)
        storage.save_state("circuit_breaker", circuit_breaker.to_dict())

        trades = storage.list_trades()
        fin_m, _ = recalculate_financial_metrics(trades, Decimal("60000.00"), Decimal(str(config.testnet_strategy_capital)), uptime_sec)
        op_m = TestnetOperationalMetrics(
            uptime_seconds=uptime_sec,
            start_time=start_time_iso,
            total_cycles=total_cycles,
            failed_cycles=failed_cycles,
            api_errors=api_errors,
        )
        return TestnetSoakCycleResult(
            timestamp=now_iso,
            cycle_status="ERROR",
            signal=Signal.HOLD,
            closed_candle_time="",
            closed_candle_timestamp=0,
            executed_order=None,
            circuit_breaker_tripped=circuit_breaker.is_tripped,
            circuit_breaker_reason=circuit_breaker.trip_reason,
            operational_metrics=op_m,
            financial_metrics=fin_m,
            message=f"Market data fetch error: {exc}",
        )

    current_price = Decimal(str(last_price_float))

    # 5. Filtragem de candles fechados e deduplicação
    closed_candles = filter_closed_candles(raw_candles, config.paper_timeframe, now_ms=now_ms)
    if not closed_candles:
        successful_cycles += 1
        circuit_breaker.record_success()
        trades = storage.list_trades()
        fin_m, pos = recalculate_financial_metrics(trades, current_price, Decimal(str(config.testnet_strategy_capital)), uptime_sec)
        op_m = TestnetOperationalMetrics(
            uptime_seconds=uptime_sec,
            start_time=start_time_iso,
            total_cycles=total_cycles,
            successful_cycles=successful_cycles,
        )
        return TestnetSoakCycleResult(
            timestamp=now_iso,
            cycle_status="HOLD",
            signal=Signal.HOLD,
            closed_candle_time="",
            closed_candle_timestamp=0,
            executed_order=None,
            circuit_breaker_tripped=circuit_breaker.is_tripped,
            circuit_breaker_reason=circuit_breaker.trip_reason,
            operational_metrics=op_m,
            financial_metrics=fin_m,
            message="Nenhum candle fechado disponível.",
        )

    latest_closed_candle = closed_candles[-1]
    last_processed_candle_ts = storage.get_state("last_processed_candle_ts", 0)

    # 6. Avaliação da Estratégia
    strat_res = evaluate_sma_crossover(
        closed_candles,
        short_window=config.short_window,
        long_window=config.long_window,
    )
    signal = strat_res.signal
    signal_reason = strat_res.reason

    current_position = storage.get_position()
    cycle_status = "HOLD"
    executed_order_result: ExchangeOrderResult | None = None
    cycle_message = f"HOLD ({signal_reason})"

    # Verificação de novo candle: previne ordem repetida no mesmo candle
    is_new_candle = latest_closed_candle.timestamp > last_processed_candle_ts

    # Se circuit breaker estiver disparado, NUNCA executa nova ordem
    if circuit_breaker.is_tripped:
        cycle_status = "BLOCKED_CIRCUIT_BREAKER"
        cycle_message = f"Novas ordens bloqueadas por Circuit Breaker: {circuit_breaker.trip_reason}"
        logger.warning(cycle_message)
    elif not is_new_candle:
        duplicate_blocks += 1
        cycle_message = f"Candle já processado (ts={latest_closed_candle.timestamp}). Ignorando repetição."
    else:
        # 7. Execução Determinística da Estratégia
        paper_acct = PaperAccount(
            usdt_balance=Decimal(str(config.testnet_strategy_capital)),
            btc_balance=current_position.quantity,
            updated_at=now_iso,
        )
        paper_pos = PaperPosition(
            side=current_position.side,
            quantity=current_position.quantity,
            cost_basis=current_position.cost_basis,
            entry_price=current_position.entry_price,
            entry_timestamp=current_position.entry_timestamp or now_iso,
        )
        soak_risk_cfg = Config(
            trading_mode=config.trading_mode,
            paper_trade_notional=float(DEFAULT_TARGET_MICRO_ORDER_NOTIONAL),
            paper_commission=config.paper_commission,
            risk_stop_loss_pct=config.risk_stop_loss_pct,
            risk_max_daily_loss=config.risk_max_daily_loss,
            risk_cooldown_candles=config.risk_cooldown_candles,
            risk_max_position_notional=config.risk_max_position_notional,
            risk_kill_switch=config.risk_kill_switch,
        )
        risk_engine = RiskEngine(config=soak_risk_cfg)
        risk_decision = risk_engine.evaluate(
            account=paper_acct,
            position=paper_pos,
            signal=signal,
            signal_reason=signal_reason,
            current_price=current_price,
            candle_timestamp=latest_closed_candle.timestamp,
            timeframe_ms=60000,
            kill_switch_active=config.risk_kill_switch,
            daily_realized_pnl=Decimal("0.00"),
            last_closed_trade_candle_ts=None,
        )

        if not risk_decision.allowed:
            cycle_message = f"Risk Engine bloqueou: {risk_decision.reason}"
        elif signal == Signal.BUY and current_position.side != "LONG":
            # Pipeline de COMPRA na Testnet
            try:
                markets = adapter.load_markets() if hasattr(adapter, "load_markets") else {}
                market_meta = markets.get(config.symbol) if isinstance(markets, dict) else None
                filters = extract_market_filters(market_meta or {
                    "symbol": config.symbol,
                    "base": "BTC",
                    "quote": "USDT",
                    "limits": {"amount": {"min": 0.00001}, "cost": {"min": 5.0}},
                    "precision": {"amount": 0.00001, "price": 0.01},
                })

                # Quantidade para micro-ordem segura ~6.0 USDT
                target_notional = DEFAULT_TARGET_MICRO_ORDER_NOTIONAL
                raw_qty = target_notional / current_price
                _, sanitized_qty, _ = sanitize_amount(raw_qty, filters.min_amount, filters.amount_step, filters.max_amount)
                if sanitized_qty < filters.min_amount:
                    sanitized_qty = filters.min_amount

                calc_notional = sanitized_qty * current_price
                corr_id = f"soak_buy_{latest_closed_candle.timestamp}_{int(time.time())}"
                intent = OrderIntent(
                    symbol=config.symbol,
                    side="BUY",
                    order_type="MARKET",
                    quantity=sanitized_qty,
                    price=None,
                    requested_notional=calc_notional,
                    strategy_name="testnet_soak",
                    strategy_version="1.0.0",
                    signal="BUY",
                    created_at=now_iso,
                    correlation_id=corr_id,
                )

                account_snapshot = AccountStateSnapshot(
                    symbol=config.symbol,
                    base_asset="BTC",
                    quote_asset="USDT",
                    base_free=Decimal("0.00"),
                    base_locked=Decimal("0.00"),
                    quote_free=Decimal("10000.00"),
                    quote_locked=Decimal("0.00"),
                    captured_at=now_iso,
                )

                guard = MarketFilterGuard(filters)
                armed_cfg = Config(
                    trading_mode="live",
                    live_trading_acknowledged=True,
                    binance_environment=BinanceEnvironment.SPOT_TESTNET,
                    testnet_execution_enabled=True,
                    live_micro_order_max_notional=config.live_micro_order_max_notional,
                    live_max_order_notional=config.live_max_order_notional,
                )
                safety_gate = LiveSafetyGate()
                safety_decision = safety_gate.evaluate(
                    intent=intent,
                    risk_decision=risk_decision,
                    market_guard=guard,
                    account_snapshot=account_snapshot,
                    config=armed_cfg,
                )

                if not safety_decision.allowed or safety_decision.approved_intent is None:
                    cycle_message = f"LiveSafetyGate bloqueou BUY: {safety_decision.reason}"
                    logger.warning(cycle_message)
                else:
                    approved_intent = safety_decision.approved_intent

                    # Executor LIVE com adapter da Testnet
                    engine = GuardedLiveExecutionEngine(
                        config=armed_cfg,
                        adapter=adapter,
                        storage=order_storage,
                    )

                    orders_created += 1
                    exec_result = engine.execute(approved_intent)

                    if exec_result.status == OrderStatus.UNKNOWN:
                        unknown_orders += 1
                        timeouts += 1
                        circuit_breaker.record_unknown_order(exec_result.client_order_id)
                        cycle_status = "UNKNOWN_ORDER_SUBMITTED"
                        cycle_message = f"Ordem {exec_result.client_order_id} retornou UNKNOWN na submissão. Circuit Breaker disparado."
                        executed_order_result = exec_result
                    else:
                        try:
                            reconciled = engine.reconcile_order(exec_result.client_order_id)
                            reconciliations += 1
                            executed_order_result = reconciled

                            if reconciled.status == OrderStatus.FILLED:
                                orders_filled += 1
                                cycle_status = "BUY_EXECUTED"
                                cycle_message = f"BUY_FILLED @ {reconciled.average_fill_price} USDT"

                                fill_price = reconciled.average_fill_price or current_price
                                qty = reconciled.executed_quantity
                                notional = reconciled.cumulative_quote_quantity or (qty * fill_price)
                                rep_fee = reconciled.fee if (reconciled.fee is not None and reconciled.fee > Decimal("0.00")) else None
                                if rep_fee is not None:
                                    eff_fee = rep_fee
                                    fee_src = "EXCHANGE"
                                    est_fee = Decimal("0.00")
                                else:
                                    eff_fee = notional * Decimal("0.0010")
                                    fee_src = "ESTIMATED"
                                    est_fee = eff_fee

                                slip_usdt = (fill_price - current_price) * qty
                                slip_bps = ((fill_price - current_price) / current_price * Decimal("10000")) if current_price > Decimal("0") else Decimal("0.00")

                                trade_rec = TestnetTradeRecord(
                                    client_order_id=reconciled.client_order_id,
                                    exchange_order_id=reconciled.exchange_order_id,
                                    timestamp=now_iso,
                                    symbol=config.symbol,
                                    side="BUY",
                                    order_type="MARKET",
                                    requested_quantity=reconciled.requested_quantity,
                                    executed_quantity=reconciled.executed_quantity,
                                    limit_price=reconciled.limit_price,
                                    average_fill_price=reconciled.average_fill_price,
                                    notional=notional,
                                    fee=eff_fee,
                                    fee_asset=reconciled.fee_asset or "USDT",
                                    exchange_reported_fee=rep_fee,
                                    estimated_fee=est_fee,
                                    fee_source=fee_src,
                                    reference_price=current_price,
                                    estimated_slippage_usdt=slip_usdt,
                                    estimated_slippage_bps=slip_bps,
                                )
                                storage.record_trade(trade_rec)
                            elif reconciled.status == OrderStatus.UNKNOWN:
                                unknown_orders += 1
                                circuit_breaker.record_unknown_order(reconciled.client_order_id)
                                cycle_status = "UNKNOWN_ORDER"
                                cycle_message = f"Ordem {reconciled.client_order_id} em estado UNKNOWN após reconciliação."
                            elif reconciled.status == OrderStatus.REJECTED:
                                orders_rejected += 1
                                cycle_status = "ORDER_REJECTED"
                                cycle_message = f"Ordem {reconciled.client_order_id} rejeitada pela exchange."
                            elif reconciled.status == OrderStatus.PARTIALLY_FILLED:
                                partial_fills += 1
                                cycle_status = "PARTIAL_FILL"
                                cycle_message = f"Ordem {reconciled.client_order_id} parcialmente preenchida."
                        except Exception as rec_exc:
                            api_errors += 1
                            circuit_breaker.record_error(f"Erro ao reconciliar BUY na Testnet: {rec_exc}")
                            logger.error("Erro na reconciliação pós-execução BUY: %s", rec_exc)

            except Exception as exc:
                api_errors += 1
                circuit_breaker.record_error(f"Erro ao submeter BUY na Testnet: {exc}")
                logger.error("Erro no ciclo BUY do Soak: %s", exc)

        elif signal == Signal.SELL and current_position.side == "LONG":
            # Pipeline de VENDA na Testnet
            try:
                markets = adapter.load_markets() if hasattr(adapter, "load_markets") else {}
                market_meta = markets.get(config.symbol) if isinstance(markets, dict) else None
                filters = extract_market_filters(market_meta or {
                    "symbol": config.symbol,
                    "base": "BTC",
                    "quote": "USDT",
                    "limits": {"amount": {"min": 0.00001}, "cost": {"min": 5.0}},
                    "precision": {"amount": 0.00001, "price": 0.01},
                })

                _, sell_qty, _ = sanitize_amount(current_position.quantity, filters.min_amount, filters.amount_step, filters.max_amount)
                if sell_qty > Decimal("0") and sell_qty >= filters.min_amount:
                    corr_id = f"soak_sell_{latest_closed_candle.timestamp}_{int(time.time())}"
                    calc_sell_notional = sell_qty * current_price
                    intent = OrderIntent(
                        symbol=config.symbol,
                        side="SELL",
                        order_type="MARKET",
                        quantity=sell_qty,
                        price=None,
                        requested_notional=calc_sell_notional,
                        strategy_name="testnet_soak",
                        strategy_version="1.0.0",
                        signal="SELL",
                        created_at=now_iso,
                        correlation_id=corr_id,
                    )

                    account_snapshot = AccountStateSnapshot(
                        symbol=config.symbol,
                        base_asset="BTC",
                        quote_asset="USDT",
                        base_free=sell_qty,
                        base_locked=Decimal("0.00"),
                        quote_free=Decimal("10000.00"),
                        quote_locked=Decimal("0.00"),
                        captured_at=now_iso,
                    )

                    guard = MarketFilterGuard(filters)
                    armed_cfg = Config(
                        trading_mode="live",
                        live_trading_acknowledged=True,
                        binance_environment=BinanceEnvironment.SPOT_TESTNET,
                        testnet_execution_enabled=True,
                        live_micro_order_max_notional=config.live_micro_order_max_notional,
                        live_max_order_notional=config.live_max_order_notional,
                    )
                    safety_gate = LiveSafetyGate()
                    safety_decision = safety_gate.evaluate(
                        intent=intent,
                        risk_decision=risk_decision,
                        market_guard=guard,
                        account_snapshot=account_snapshot,
                        config=armed_cfg,
                    )

                    if not safety_decision.allowed or safety_decision.approved_intent is None:
                        cycle_message = f"LiveSafetyGate bloqueou SELL: {safety_decision.reason}"
                        logger.warning(cycle_message)
                    else:
                        approved_intent = safety_decision.approved_intent

                        engine = GuardedLiveExecutionEngine(
                            config=armed_cfg,
                            adapter=adapter,
                            storage=order_storage,
                        )

                        orders_created += 1
                        exec_result = engine.execute(approved_intent)

                        if exec_result.status == OrderStatus.UNKNOWN:
                            unknown_orders += 1
                            timeouts += 1
                            circuit_breaker.record_unknown_order(exec_result.client_order_id)
                            cycle_status = "UNKNOWN_ORDER_SUBMITTED"
                            cycle_message = f"Ordem {exec_result.client_order_id} retornou UNKNOWN na submissão. Circuit Breaker disparado."
                            executed_order_result = exec_result
                        else:
                            try:
                                reconciled = engine.reconcile_order(exec_result.client_order_id)
                                reconciliations += 1
                                executed_order_result = reconciled

                                if reconciled.status == OrderStatus.FILLED:
                                    orders_filled += 1
                                    cycle_status = "SELL_EXECUTED"
                                    cycle_message = f"SELL_FILLED @ {reconciled.average_fill_price} USDT"

                                    fill_price = reconciled.average_fill_price or current_price
                                    qty = reconciled.executed_quantity
                                    notional = reconciled.cumulative_quote_quantity or (qty * fill_price)
                                    rep_fee = reconciled.fee if (reconciled.fee is not None and reconciled.fee > Decimal("0.00")) else None
                                    if rep_fee is not None:
                                        eff_fee = rep_fee
                                        fee_src = "EXCHANGE"
                                        est_fee = Decimal("0.00")
                                    else:
                                        eff_fee = notional * Decimal("0.0010")
                                        fee_src = "ESTIMATED"
                                        est_fee = eff_fee

                                    slip_usdt = (current_price - fill_price) * qty
                                    slip_bps = ((current_price - fill_price) / current_price * Decimal("10000")) if current_price > Decimal("0") else Decimal("0.00")

                                    gross_proc = qty * fill_price
                                    realized_pnl = gross_proc - current_position.cost_basis - eff_fee

                                    trade_rec = TestnetTradeRecord(
                                        client_order_id=reconciled.client_order_id,
                                        exchange_order_id=reconciled.exchange_order_id,
                                        timestamp=now_iso,
                                        symbol=config.symbol,
                                        side="SELL",
                                        order_type="MARKET",
                                        requested_quantity=reconciled.requested_quantity,
                                        executed_quantity=reconciled.executed_quantity,
                                        limit_price=reconciled.limit_price,
                                        average_fill_price=reconciled.average_fill_price,
                                        notional=notional,
                                        fee=eff_fee,
                                        fee_asset=reconciled.fee_asset or "USDT",
                                        realized_pnl=realized_pnl,
                                        exit_reason=signal_reason,
                                        exchange_reported_fee=rep_fee,
                                        estimated_fee=est_fee,
                                        fee_source=fee_src,
                                        reference_price=current_price,
                                        estimated_slippage_usdt=slip_usdt,
                                        estimated_slippage_bps=slip_bps,
                                    )
                                    storage.record_trade(trade_rec)
                                elif reconciled.status == OrderStatus.UNKNOWN:
                                    unknown_orders += 1
                                    circuit_breaker.record_unknown_order(reconciled.client_order_id)
                                    cycle_status = "UNKNOWN_ORDER"
                                    cycle_message = f"Ordem {reconciled.client_order_id} em estado UNKNOWN após reconciliação."
                                elif reconciled.status == OrderStatus.REJECTED:
                                    orders_rejected += 1
                                    cycle_status = "ORDER_REJECTED"
                                    cycle_message = f"Ordem {reconciled.client_order_id} rejeitada pela exchange."
                                elif reconciled.status == OrderStatus.PARTIALLY_FILLED:
                                    partial_fills += 1
                                    cycle_status = "PARTIAL_FILL"
                                    cycle_message = f"Ordem {reconciled.client_order_id} parcialmente preenchida."
                            except Exception as rec_exc:
                                api_errors += 1
                                circuit_breaker.record_error(f"Erro ao reconciliar SELL na Testnet: {rec_exc}")
                                logger.error("Erro na reconciliação pós-execução SELL: %s", rec_exc)

            except Exception as exc:
                api_errors += 1
                circuit_breaker.record_error(f"Erro ao submeter SELL na Testnet: {exc}")
                logger.error("Erro no ciclo SELL do Soak: %s", exc)

    # 8. Atualização e Persistência do Checkpoint
    if not circuit_breaker.is_tripped and api_errors == 0 and unknown_orders == 0:
        successful_cycles += 1
        circuit_breaker.record_success()
        storage.save_state("last_successful_cycle", now_iso)
    else:
        failed_cycles += 1

    storage.save_state("start_time", start_time_iso)
    storage.save_state("total_cycles", total_cycles)
    storage.save_state("successful_cycles", successful_cycles)
    storage.save_state("failed_cycles", failed_cycles)
    storage.save_state("api_errors", api_errors)
    storage.save_state("timeouts", timeouts)
    storage.save_state("reconciliations", reconciliations)
    storage.save_state("unknown_orders", unknown_orders)
    storage.save_state("orphan_orders", orphan_orders)
    storage.save_state("duplicate_blocks", duplicate_blocks)
    storage.save_state("orders_created", orders_created)
    storage.save_state("orders_filled", orders_filled)
    storage.save_state("orders_canceled", orders_canceled)
    storage.save_state("orders_rejected", orders_rejected)
    storage.save_state("partial_fills", partial_fills)
    storage.save_state("last_processed_candle_ts", latest_closed_candle.timestamp)
    storage.save_state("circuit_breaker", circuit_breaker.to_dict())
    storage.save_state("last_heartbeat", now_iso)
    storage.save_state("last_cycle_at", now_iso)

    # 9. Recalcula PnL e Métricas Financeiras
    trades = storage.list_trades()
    fin_metrics, updated_pos = recalculate_financial_metrics(
        trades=trades,
        current_price=current_price,
        strategy_capital=Decimal(str(config.testnet_strategy_capital)),
        observation_period_seconds=uptime_sec,
    )
    storage.save_position(updated_pos)

    op_metrics = TestnetOperationalMetrics(
        uptime_seconds=uptime_sec,
        start_time=start_time_iso,
        last_successful_cycle=now_iso,
        total_cycles=total_cycles,
        successful_cycles=successful_cycles,
        failed_cycles=failed_cycles,
        api_errors=api_errors,
        timeouts=timeouts,
        reconciliations=reconciliations,
        unknown_orders=unknown_orders,
        orphan_orders=orphan_orders,
        duplicate_blocks=duplicate_blocks,
        orders_created=orders_created,
        orders_filled=orders_filled,
        orders_canceled=orders_canceled,
        orders_rejected=orders_rejected,
        partial_fills=partial_fills,
    )

    storage.save_metrics_snapshot(op_metrics, fin_metrics)

    return TestnetSoakCycleResult(
        timestamp=now_iso,
        cycle_status=cycle_status,
        signal=signal,
        closed_candle_time=str(latest_closed_candle.timestamp),
        closed_candle_timestamp=latest_closed_candle.timestamp,
        executed_order=executed_order_result,
        circuit_breaker_tripped=circuit_breaker.is_tripped,
        circuit_breaker_reason=circuit_breaker.trip_reason,
        operational_metrics=op_metrics,
        financial_metrics=fin_metrics,
        message=cycle_message,
    )


# =============================================================================
# COMANDO READ-ONLY DE PREVIEW (100% SEGURO)
# =============================================================================

def run_testnet_soak_preview(
    config: Config,
    storage: TestnetSoakStorage | None = None,
    adapter: ExchangeOrderAdapter | None = None,
    credential_provider: WindowsCredentialProvider | None = None,
) -> int:
    """Executa a checagem preliminar em modo PREVIEW (100% read-only)."""
    print("=" * 65)
    print("TESTNET SOAK — DRY PREVIEW (READ-ONLY)")
    print("=" * 65)

    if storage is None:
        storage = TestnetSoakStorage(config.testnet_soak_db_path)

    cb_dict = storage.get_state("circuit_breaker", {})
    cb = TestnetCircuitBreaker.from_dict(cb_dict) if isinstance(cb_dict, dict) else TestnetCircuitBreaker()

    if credential_provider is None:
        credential_provider = WindowsCredentialProvider.for_environment(BinanceEnvironment.SPOT_TESTNET)

    has_creds = False
    api_key = ""
    api_secret = ""
    if hasattr(credential_provider, "has_binance_credentials"):
        has_creds = credential_provider.has_binance_credentials()
        if has_creds:
            c = credential_provider.get_binance_credentials()
            api_key = c.api_key
            api_secret = c.api_secret
    elif hasattr(credential_provider, "get_credentials"):
        c = credential_provider.get_credentials()
        if c:
            has_creds = True
            api_key = getattr(c, "api_key", "")
            api_secret = getattr(c, "api_secret", "")

    cred_status = "PRESENT" if has_creds else "MISSING"

    if adapter is None and has_creds:
        adapter = BinanceSpotTestnetOrderAdapter(
            credential_provider=credential_provider,
            testnet_execution_enabled=False,
        )

    print(f"ENVIRONMENT                    : {config.binance_environment.value.upper()}")
    print(f"TESTNET_CREDENTIALS            : {cred_status}")
    print(f"TARGET_STORE                   : {credential_provider.target_name}")
    print(f"SYMBOL                         : {config.symbol}")
    print(f"TIMEFRAME                      : {config.paper_timeframe}")
    print(f"STRATEGY_CAPITAL               : {config.testnet_strategy_capital:.2f} USDT")
    print(f"MICRO_ORDER_CAP                : {config.live_micro_order_max_notional:.2f} USDT")
    print(f"CIRCUIT_BREAKER_STATUS         : {'TRIPPED' if cb.is_tripped else 'CLEAR'}")
    if cb.is_tripped:
        print(f"CIRCUIT_BREAKER_REASON         : {cb.trip_reason}")

    # Passagem defensiva de sentries em modo preview
    sentry_ok = True
    try:
        cfg_test = Config(
            binance_environment=BinanceEnvironment.SPOT_TESTNET,
            testnet_execution_enabled=True,
            real_order_submission_enabled=False,
        )
        verify_testnet_soak_sentries(cfg_test, adapter, credential_provider)
        print("SENTRY_VERIFICATION            : PASS")
    except Exception as e:
        sentry_ok = False
        print(f"SENTRY_VERIFICATION            : FAIL ({e})")

    print("-" * 65)
    print("INVIOLABILIDADE OPERACIONAL:")
    print("TESTNET_WRITE_EXECUTED         : NO")
    print("PRODUCTION_ORDERS_SENT         : 0")
    print("PRODUCTION_WRITE_ENABLED       : NO")
    print(f"SOAK_ARMED                     : {'YES' if config.testnet_execution_enabled else 'NO'}")
    print(f"READY_TO_START_TESTNET_SOAK    : {'YES' if (sentry_ok and cred_status == 'PRESENT' and not cb.is_tripped) else 'NO'}")
    print("=" * 65)
    return 0


# =============================================================================
# COMANDO READ-ONLY DE STATUS (TESTNET_SOAK_STATUS)
# =============================================================================

def print_testnet_soak_status(storage: TestnetSoakStorage | None = None, db_path: str = "data/finbot_testnet_soak.sqlite3") -> int:
    """Imprime o relatório consolidado de saúde e métricas sem expor secrets."""
    if storage is None:
        storage = TestnetSoakStorage(db_path)

    latest = storage.get_latest_metrics()
    cb_data = storage.get_state("circuit_breaker", {})
    cb = TestnetCircuitBreaker.from_dict(cb_data) if isinstance(cb_data, dict) else TestnetCircuitBreaker()
    pos = storage.get_position()
    status_str = determine_runner_status(storage, cb)

    print("=" * 65)
    print("TESTNET_SOAK_STATUS")
    print("=" * 65)

    if latest is None:
        print("Nenhuma métrica persistida ainda no banco de dados.")
        print(f"STATUS                         : {status_str} (Sem histórico em {db_path})")
        print(f"CIRCUIT_BREAKER_TRIPPED        : {'YES' if cb.is_tripped else 'NO'}")
        print("PRODUCTION_WRITE_ENABLED       : NO")
        print("=" * 65)
        return 0

    det = latest.get("details", {})
    op = det.get("operational", {})
    fin = det.get("financial", {})

    uptime_sec = float(latest.get("uptime_seconds", 0.0))
    hours = int(uptime_sec // 3600)
    minutes = int((uptime_sec % 3600) // 60)
    seconds = int(uptime_sec % 60)
    uptime_fmt = f"{hours:02d}h {minutes:02d}m {seconds:02d}s ({uptime_sec:.0f}s)"

    print(f"STATUS                         : {status_str}")
    print(f"UPTIME                         : {uptime_fmt}")
    print(f"TOTAL_CYCLES                   : {latest.get('total_cycles', 0)}")
    print(f"TOTAL_TRADES                   : {fin.get('total_trades', 0)}")
    print(f"ORDERS_FILLED                  : {latest.get('orders_filled', 0)}")
    print(f"UNKNOWN_ORDERS                 : {latest.get('unknown_orders', 0)}")
    print(f"ORPHAN_ORDERS                  : {latest.get('orphan_orders', 0)}")
    print(f"API_ERRORS                     : {latest.get('api_errors', 0)}")
    print(f"CIRCUIT_BREAKER_TRIPPED        : {'YES' if cb.is_tripped else 'NO'}")
    if cb.is_tripped:
        print(f"CIRCUIT_BREAKER_REASON         : {cb.trip_reason}")

    print("-" * 65)
    print("FINANCEIRO & ESTRATÉGIA (CAPITAL NORMALIZADO):")
    strat_cap = fin.get("strategy_capital", "100.00")
    print(f"STARTING_EQUITY                : {strat_cap} USDT")
    print(f"CURRENT_EQUITY                 : {latest.get('current_equity', '0.00')} USDT")
    print(f"REALIZED_PNL                   : {fin.get('realized_pnl', '0.00')} USDT")
    print(f"UNREALIZED_PNL                 : {fin.get('unrealized_pnl', '0.00')} USDT")
    print(f"NET_PNL                        : {latest.get('net_pnl', '0.00')} USDT")
    print(f"FEES (EXCHANGE_REPORTED)       : {fin.get('exchange_reported_fees', '0.00')} USDT")
    print(f"FEES (ESTIMATED)               : {fin.get('estimated_fees', '0.00')} USDT")
    print(f"TOTAL_FEES                     : {fin.get('fees', '0.00')} USDT")
    print(f"ESTIMATED_SLIPPAGE             : {fin.get('estimated_slippage', '0.00')} USDT ({fin.get('estimated_slippage_bps', '0.00')} bps)")
    print(f"NET_RETURN                     : {latest.get('net_return_pct', 0.0):.2f}%")
    print(f"MAX_DRAWDOWN                   : {latest.get('max_drawdown_pct', 0.0):.2f}%")
    print(f"WIN_RATE                       : {fin.get('win_rate_pct', 0.0):.2f}%")
    print(f"PROFIT_FACTOR                  : {fin.get('profit_factor', 0.0):.2f}")
    avg_w = fin.get("average_win")
    avg_l = fin.get("average_loss")
    exp_v = fin.get("expectancy")
    print(f"AVERAGE_WIN                    : {avg_w if avg_w is not None else 'N/A'} USDT")
    print(f"AVERAGE_LOSS                   : {avg_l if avg_l is not None else 'N/A'} USDT")
    print(f"EXPECTANCY                     : {exp_v if exp_v is not None else 'N/A'} USDT/trade")
    print(f"POSIÇÃO ABERTA                 : {pos.side} ({pos.quantity} BTC)")

    print("-" * 65)
    print("QUALIDADE ESTATÍSTICA (EVIDÊNCIA LIVE_CAPITAL_GATE):")
    print(f"TRADE_SAMPLE_SIZE              : {fin.get('closed_trades', 0)}")
    obs_sec = float(fin.get("observation_period_seconds", 0.0) or uptime_sec)
    print(f"OBSERVATION_PERIOD             : {obs_sec:.0f}s ({obs_sec/3600:.1f}h)")
    print(f"FIRST_TRADE_AT                 : {fin.get('first_trade_at') or 'N/A'}")
    print(f"LAST_TRADE_AT                  : {fin.get('last_trade_at') or 'N/A'}")
    print("LIVE_CAPITAL_GATE_STATUS       : PENDENTE (Em coleta de evidência prolongada)")

    print("-" * 65)
    print("INVIOLABILIDADE OPERACIONAL:")
    print("ENVIRONMENT                    : SPOT_TESTNET")
    print("PRODUCTION_ORDERS_SENT         : 0")
    print("PRODUCTION_WRITE_ENABLED       : NO")
    print("=" * 65)
    return 0


# =============================================================================
# RUNNER CONTÍNUO COM GRACEFUL SHUTDOWN
# =============================================================================

def run_testnet_soak_continuous(
    config: Config,
    storage: TestnetSoakStorage,
    order_storage: LiveOrderStorage,
    adapter: ExchangeOrderAdapter,
    circuit_breaker: TestnetCircuitBreaker,
    credential_provider: WindowsCredentialProvider | None = None,
    cycle_interval_seconds: float = 60.0,
    stop_event: threading.Event | None = None,
    max_cycles: int | None = None,
) -> int:
    """Executa o loop contínuo do Soak com gerenciamento de lifecycle e graceful shutdown.

    Garantias:
    - Marca runner_status como RUNNING no início e atualiza heartbeat a cada ciclo.
    - Ao encerrar por Ctrl+C, KeyboardInterrupt, SIGINT/SIGTERM ou normal:
      * Marca runner_status como STOPPED;
      * Persiste o último checkpoint de estado;
      * Preserva posições abertas válidas e ordens UNKNOWN (para reconciliação futura);
      * Fecha o banco SQLite e conexões adequadamente;
      * Zero ordens adicionais criadas durante o shutdown.
    """
    logger.info("Iniciando runner contínuo do Testnet Soak...")
    storage.save_state("runner_status", "RUNNING")
    storage.save_state("last_heartbeat", datetime.now(timezone.utc).isoformat())

    cycles_completed = 0
    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                logger.info("Sinal de parada detectado via stop_event.")
                break

            now_iso = datetime.now(timezone.utc).isoformat()
            storage.save_state("runner_status", "RUNNING")
            storage.save_state("last_heartbeat", now_iso)

            res = execute_testnet_soak_cycle(
                config=config,
                storage=storage,
                order_storage=order_storage,
                adapter=adapter,
                circuit_breaker=circuit_breaker,
                credential_provider=credential_provider,
            )
            cycles_completed += 1
            logger.info("Ciclo Soak #%d: %s | %s", cycles_completed, res.cycle_status, res.message)

            if max_cycles is not None and cycles_completed >= max_cycles:
                logger.info("Atingido número máximo de ciclos (%d). Encerrando normalmente.", max_cycles)
                break

            # Aguarda intervalo respeitando stop_event
            if stop_event is not None:
                if stop_event.wait(timeout=cycle_interval_seconds):
                    break
            else:
                time.sleep(cycle_interval_seconds)

    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Interrupção pelo operador (Ctrl+C). Executando encerramento gracioso...")
        logger.info("KeyboardInterrupt recebido no runner contínuo.")
    except Exception as exc:
        print(f"\n[SHUTDOWN] Exceção não tratada no runner: {exc}")
        logger.error("Exceção no runner contínuo: %s", exc)
    finally:
        # Encerramento gracioso
        shutdown_ts = datetime.now(timezone.utc).isoformat()
        logger.info("Executando procedimentos de graceful shutdown...")
        storage.save_state("runner_status", "STOPPED")
        storage.save_state("last_heartbeat", shutdown_ts)
        storage.save_state("shutdown_at", shutdown_ts)
        try:
            storage.close()
        except Exception as e:
            logger.warning("Erro ao fechar storage: %s", e)
        print("[SHUTDOWN] Runner finalizado com sucesso. STATUS = STOPPED.")

    return 0


# =============================================================================
# CLI ENTRYPOINT
# =============================================================================

def main(argv: list[str] | None = None) -> int:
    """Ponto de entrada do comando operacional python -m finbot.testnet_soak."""
    parser = argparse.ArgumentParser(description="FinBot — Binance Spot Testnet Soak & Metrics")
    parser.add_argument("--status", action="store_true", help="Exibe relatório read-only de status e métricas do Soak.")
    parser.add_argument("--confirm-testnet-soak", action="store_true", help="Arma a execução contínua na Testnet.")
    parser.add_argument("--once", action="store_true", help="Executa um único ciclo e encerra.")
    parser.add_argument("--reset-circuit-breaker", action="store_true", help="Reinicia o disjuntor de segurança.")
    parser.add_argument("--db-path", type=str, default="data/finbot_testnet_soak.sqlite3", help="Caminho do banco SQLite do Soak.")
    parser.add_argument("--strategy-capital", type=float, default=100.0, help="Capital virtual normalizado em USDT.")

    args = parser.parse_args(argv)
    setup_logging(log_level="INFO")

    storage = TestnetSoakStorage(args.db_path)

    # 1. Reset de Circuit Breaker
    if args.reset_circuit_breaker:
        cb_data = storage.get_state("circuit_breaker", {})
        cb = TestnetCircuitBreaker.from_dict(cb_data) if isinstance(cb_data, dict) else TestnetCircuitBreaker()
        cb.reset()
        storage.save_state("circuit_breaker", cb.to_dict())
        storage.close()
        print("Circuit breaker reiniciado com sucesso.")
        return 0

    # 2. Relatório de Status
    if args.status:
        ret = print_testnet_soak_status(storage=storage, db_path=args.db_path)
        storage.close()
        return ret

    base_cfg = get_config()
    cfg = Config(
        trading_mode="live",
        binance_environment=BinanceEnvironment.SPOT_TESTNET,
        testnet_execution_enabled=args.confirm_testnet_soak,
        live_execution_enabled=False,
        real_order_submission_enabled=False,
        testnet_strategy_capital=args.strategy_capital,
        testnet_soak_db_path=args.db_path,
        symbol=base_cfg.symbol,
        paper_timeframe=base_cfg.paper_timeframe,
    )

    # 3. Modo Preview por Padrão (Sem --confirm-testnet-soak)
    if not args.confirm_testnet_soak:
        ret = run_testnet_soak_preview(cfg, storage=storage)
        storage.close()
        return ret

    # 4. Modo Armado de Execução
    print("=" * 65)
    print("INICIANDO BINANCE SPOT TESTNET SOAK (ARMADO)")
    print("=" * 65)

    cred_provider = WindowsCredentialProvider.for_environment(BinanceEnvironment.SPOT_TESTNET)
    if not cred_provider.has_binance_credentials():
        print("ERRO CRÍTICO: Credenciais Testnet não encontradas no Windows Credential Manager.")
        storage.close()
        return 1

    adapter = BinanceSpotTestnetOrderAdapter(
        credential_provider=cred_provider,
        testnet_execution_enabled=True,
    )
    order_storage = LiveOrderStorage("data/finbot_live_orders.sqlite3")

    cb_data = storage.get_state("circuit_breaker", {})
    cb = TestnetCircuitBreaker.from_dict(cb_data) if isinstance(cb_data, dict) else TestnetCircuitBreaker()

    if args.once:
        storage.save_state("runner_status", "STOPPED")
        storage.save_state("last_heartbeat", datetime.now(timezone.utc).isoformat())
        try:
            res = execute_testnet_soak_cycle(
                config=cfg,
                storage=storage,
                order_storage=order_storage,
                adapter=adapter,
                circuit_breaker=cb,
                credential_provider=cred_provider,
            )
            print(f"Ciclo executado: {res.cycle_status} | {res.message}")
        finally:
            storage.save_state("runner_status", "STOPPED")
            storage.close()
        return 0

    print("Soak contínuo iniciado. Pressione Ctrl+C para encerrar.")
    return run_testnet_soak_continuous(
        config=cfg,
        storage=storage,
        order_storage=order_storage,
        adapter=adapter,
        circuit_breaker=cb,
        credential_provider=cred_provider,
        cycle_interval_seconds=60.0,
    )


if __name__ == "__main__":
    sys.exit(main())

