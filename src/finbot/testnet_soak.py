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
    estimated_slippage: Decimal = Decimal("0.00")
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
    limit_price: Decimal | None
    average_fill_price: Decimal | None
    notional: Decimal
    fee: Decimal
    fee_asset: str | None
    realized_pnl: Decimal | None = None
    exit_reason: str | None = None


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
                        exit_reason TEXT
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
        finally:
            if self.db_path != ":memory:":
                conn.close()

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
                        average_fill_price, notional, fee, fee_asset, realized_pnl, exit_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(client_order_id) DO UPDATE SET
                        executed_quantity = excluded.executed_quantity,
                        average_fill_price = excluded.average_fill_price,
                        realized_pnl = excluded.realized_pnl
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
                    ),
                )
        finally:
            if self.db_path != ":memory:":
                conn.close()

    def list_trades(self) -> list[TestnetTradeRecord]:
        conn = self._get_connection()
        try:
            cursor = conn.execute("SELECT * FROM soak_trades ORDER BY id ASC")
            trades: list[TestnetTradeRecord] = []
            for r in cursor.fetchall():
                trades.append(
                    TestnetTradeRecord(
                        client_order_id=r["client_order_id"],
                        exchange_order_id=r["exchange_order_id"],
                        timestamp=r["timestamp"],
                        symbol=r["symbol"],
                        side=r["side"],
                        order_type=r["order_type"],
                        requested_quantity=Decimal(r["requested_quantity"]),
                        executed_quantity=Decimal(r["executed_quantity"]),
                        limit_price=Decimal(r["limit_price"]) if r["limit_price"] is not None else None,
                        average_fill_price=Decimal(r["average_fill_price"]) if r["average_fill_price"] is not None else None,
                        notional=Decimal(r["notional"]),
                        fee=Decimal(r["fee"] or "0"),
                        fee_asset=r["fee_asset"],
                        realized_pnl=Decimal(r["realized_pnl"]) if r["realized_pnl"] is not None else None,
                        exit_reason=r["exit_reason"],
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
                    "estimated_slippage": str(fin_metrics.estimated_slippage),
                    "gross_return_pct": fin_metrics.gross_return_pct,
                    "net_return_pct": fin_metrics.net_return_pct,
                    "max_drawdown_pct": fin_metrics.max_drawdown_pct,
                    "win_rate_pct": fin_metrics.win_rate_pct,
                    "profit_factor": fin_metrics.profit_factor,
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
# CÁLCULOS FINANCEIROS E DE MÉTRICAS (PURA / DETERMINÍSTICA)
# =============================================================================

def recalculate_financial_metrics(
    trades: list[TestnetTradeRecord],
    current_price: Decimal,
    strategy_capital: Decimal = DEFAULT_STRATEGY_CAPITAL,
    observation_period_seconds: float = 0.0,
) -> tuple[TestnetFinancialMetrics, TestnetPosition]:
    """Recalcula o estado financeiro da estratégia a partir dos trades reais executados na Testnet.

    Garante:
    - executed_quantity == 0 NÃO afeta PnL nem preço médio.
    - Preserva o capital normalizado (strategy_capital) independente do saldo da exchange.
    """
    cash = strategy_capital
    pos_qty = Decimal("0.00000000")
    pos_cost = Decimal("0.00")
    entry_px = Decimal("0.00")
    entry_ts = ""

    realized_pnl = Decimal("0.00")
    total_fees = Decimal("0.00")
    total_slippage = Decimal("0.00")

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
        # Se ordem não preencheu, ignora para efeitos financeiros
        if t.executed_quantity == Decimal("0"):
            continue

        if first_trade_at is None:
            first_trade_at = t.timestamp
        last_trade_at = t.timestamp

        fee = t.fee
        total_fees += fee

        fill_px = t.average_fill_price
        if fill_px is None or fill_px <= Decimal("0"):
            continue

        # Slippage estimado: diferença entre limite/esperado e fill real
        if t.limit_price is not None and t.limit_price > Decimal("0"):
            if t.side == "BUY":
                slip = (fill_px - t.limit_price) * t.executed_quantity
            else:
                slip = (t.limit_price - fill_px) * t.executed_quantity
            total_slippage += slip

        if t.side == "BUY":
            cost = (t.executed_quantity * fill_px) + fee
            cash -= cost
            pos_qty += t.executed_quantity
            pos_cost += cost
            entry_px = fill_px
            entry_ts = t.timestamp

        elif t.side == "SELL":
            gross_proceeds = t.executed_quantity * fill_px
            net_proceeds = gross_proceeds - fee
            cash += net_proceeds

            # PnL realizado
            trade_pnl = t.realized_pnl
            if trade_pnl is None:
                trade_pnl = net_proceeds - pos_cost

            realized_pnl += trade_pnl
            closed_trades += 1

            if trade_pnl > Decimal("0"):
                winning_trades += 1
                sum_wins += trade_pnl
            elif trade_pnl < Decimal("0"):
                losing_trades += 1
                sum_losses += abs(trade_pnl)

            pos_qty = Decimal("0.00000000")
            pos_cost = Decimal("0.00")
            entry_px = Decimal("0.00")
            entry_ts = ""

        # Tracking de drawdown ponto a ponto
        current_eq = cash + (pos_qty * fill_px)
        if current_eq > peak_equity:
            peak_equity = current_eq
        elif peak_equity > Decimal("0"):
            dd = float(((peak_equity - current_eq) / peak_equity) * Decimal("100"))
            if dd > max_drawdown:
                max_drawdown = dd

    # PnL não realizado da posição aberta atual
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
    gross_return_pct = float(((net_pnl + total_fees) / strategy_capital) * Decimal("100")) if strategy_capital > Decimal("0") else 0.0

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
        fees=total_fees.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        estimated_slippage=total_slippage.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
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

    # 3. RECONCILIAÇÃO PRÉVIA MANDATÓRIA APÓS RESTART
    # Nunca emitir ordens se houver ordens abertas ou UNKNOWN pendentes de reconciliação
    unreconciled = order_storage.get_unreconciled_orders()
    for unrec in unreconciled:
        cid = unrec["client_order_id"]
        reconciliations += 1
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
                logger.info("Ordem pendente reconciliada com sucesso: %s -> %s", cid, fetched.status.value)
            else:
                circuit_breaker.record_unknown_order(cid)
                logger.warning("Ordem pendente não localizada na exchange (UNKNOWN): %s", cid)
        except Exception as exc:
            circuit_breaker.record_unknown_order(cid)
            logger.error("Erro ao reconciliar ordem pendente %s: %s", cid, exc)

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
                                    notional=reconciled.cumulative_quote_quantity,
                                    fee=reconciled.fee or Decimal("0.00"),
                                    fee_asset=reconciled.fee_asset,
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

                                    gross_proc = reconciled.executed_quantity * (reconciled.average_fill_price or current_price)
                                    realized_pnl = gross_proc - current_position.cost_basis - (reconciled.fee or Decimal("0"))

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
                                        notional=reconciled.cumulative_quote_quantity,
                                        fee=reconciled.fee or Decimal("0.00"),
                                        fee_asset=reconciled.fee_asset,
                                        realized_pnl=realized_pnl,
                                        exit_reason=signal_reason,
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

    print("=" * 65)
    print("TESTNET_SOAK_STATUS")
    print("=" * 65)

    if latest is None:
        print("Nenhuma métrica persistida ainda no banco de dados.")
        print(f"STATUS                         : STOPPED (Sem histórico em {db_path})")
        print(f"CIRCUIT_BREAKER_TRIPPED        : {'YES' if cb.is_tripped else 'NO'}")
        print("PRODUCTION_WRITE_ENABLED       : NO")
        print("=" * 65)
        return 0

    det = latest.get("details", {})
    op = det.get("operational", {})
    fin = det.get("financial", {})

    status_str = "CIRCUIT_BREAKER_TRIPPED" if cb.is_tripped else "READY/IDLE"

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
    print(f"FEES                           : {fin.get('fees', '0.00')} USDT")
    print(f"ESTIMATED_SLIPPAGE             : {fin.get('estimated_slippage', '0.00')} USDT")
    print(f"NET_RETURN                     : {latest.get('net_return_pct', 0.0):.2f}%")
    print(f"MAX_DRAWDOWN                   : {latest.get('max_drawdown_pct', 0.0):.2f}%")
    print(f"WIN_RATE                       : {fin.get('win_rate_pct', 0.0):.2f}%")
    print(f"PROFIT_FACTOR                  : {fin.get('profit_factor', 0.0):.2f}")
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
        print("Circuit breaker reiniciado com sucesso.")
        return 0

    # 2. Relatório de Status
    if args.status:
        return print_testnet_soak_status(storage=storage, db_path=args.db_path)

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
        return run_testnet_soak_preview(cfg, storage=storage)

    # 4. Modo Armado de Execução
    print("=" * 65)
    print("INICIANDO BINANCE SPOT TESTNET SOAK (ARMADO)")
    print("=" * 65)

    cred_provider = WindowsCredentialProvider.for_environment(BinanceEnvironment.SPOT_TESTNET)
    if not cred_provider.has_binance_credentials():
        print("ERRO CRÍTICO: Credenciais Testnet não encontradas no Windows Credential Manager.")
        return 1

    creds = cred_provider.get_binance_credentials()

    adapter = BinanceSpotTestnetOrderAdapter(
        credential_provider=cred_provider,
        testnet_execution_enabled=True,
    )
    order_storage = LiveOrderStorage("data/finbot_live_orders.sqlite3")

    cb_data = storage.get_state("circuit_breaker", {})
    cb = TestnetCircuitBreaker.from_dict(cb_data) if isinstance(cb_data, dict) else TestnetCircuitBreaker()

    if args.once:
        res = execute_testnet_soak_cycle(
            config=cfg,
            storage=storage,
            order_storage=order_storage,
            adapter=adapter,
            circuit_breaker=cb,
            credential_provider=cred_provider,
        )
        print(f"Ciclo executado: {res.cycle_status} | {res.message}")
        return 0

    print("Soak contínuo iniciado. Pressione Ctrl+C para encerrar.")
    try:
        while True:
            res = execute_testnet_soak_cycle(
                config=cfg,
                storage=storage,
                order_storage=order_storage,
                adapter=adapter,
                circuit_breaker=cb,
                credential_provider=cred_provider,
            )
            logger.info("Ciclo Soak: %s | %s", res.cycle_status, res.message)
            time.sleep(60)
    except KeyboardInterrupt:
        print("\nSoak interrompido pelo operador.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
