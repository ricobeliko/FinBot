"""Módulo do executor de ordens Live Guarded — FASE 8.4B.

Este módulo implementa a infraestrutura para futura execução controlada de micro-ordens
na Binance Spot sob o princípio de defesa em profundidade e fail-closed.

REGRAS CONSTITUCIONAIS:
- ZERO REAL ORDERS: Nenhuma ordem real é enviada nesta fase.
- TRIPLE ARMING: trading_mode=='live', live_trading_acknowledged==True, live_execution_enabled==True.
- MICRO-ORDER CAP: Limite financeiro específico e conservador (default 15 USDT).
- AMBIGUOUS FAILURE: UNKNOWN != FAILED e TIMEOUT != SAFE TO RETRY.
  Falhas de rede durante submissão geram status UNKNOWN e exigem reconciliação por clientOrderId.
  Auto-retry é CATEGORICAMENTE PROIBIDO.
- FINAL LIVE BARRIER: BinanceOrderAdapter bloqueado por RealOrderSubmissionBlockedError.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
import json
from pathlib import Path
import sqlite3
from typing import Any, Protocol

from finbot.config import BinanceEnvironment, Config
from finbot.execution import (
    InvalidExecutionIntentError,
    build_order_payload,
    generate_client_order_id,
)
from finbot.live_safety import ApprovedOrderIntent
from finbot.private_exchange import BinancePrivateExchange


class OrderStatus(str, Enum):
    """Estados do ciclo de vida determinístico de uma ordem."""

    PREPARED = "PREPARED"
    PENDING_SUBMISSION = "PENDING_SUBMISSION"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


class RealOrderSubmissionBlockedError(RuntimeError):
    """Lançado se qualquer tentativa de envio real à Binance for solicitada na FASE 8.4B."""

    pass


class LiveExecutionArmingError(RuntimeError):
    """Lançado se os critérios de Triple Live Arming não forem satisfeitos."""

    pass


class MicroOrderCapExceededError(ValueError):
    """Lançado quando uma ordem excede o limite financeiro de micro-ordem."""

    pass


class OrderNotCancelableError(RuntimeError):
    """Lançado ao tentar cancelar uma ordem não cancelável ou em estado UNKNOWN sem reconciliação."""

    pass


class AmbiguousExecutionError(RuntimeError):
    """Lançado quando ocorre falha de rede/timeout durante envio, exigindo reconciliação."""

    pass


@dataclass(frozen=True)
class ExchangeOrderResult:
    """Resultado imutável retornado pelo adapter da exchange."""

    client_order_id: str
    exchange_order_id: str | None
    status: OrderStatus
    symbol: str
    side: str
    order_type: str
    requested_quantity: Decimal
    executed_quantity: Decimal
    cumulative_quote_quantity: Decimal
    average_price: Decimal | None
    fee: Decimal | None = None
    fee_asset: str | None = None
    created_at: str = ""
    updated_at: str = ""
    raw_response: dict[str, Any] | None = None


@dataclass(frozen=True)
class OrderLifecycleRecord:
    """Registro auditável imutável de transição de estado da ordem."""

    correlation_id: str
    client_order_id: str
    previous_status: OrderStatus | None
    new_status: OrderStatus
    timestamp: str
    reason: str
    details: dict[str, Any] | None = None


class ExchangeOrderAdapter(Protocol):
    """Interface/Protocolo para adapters de execução de ordens na exchange."""

    def submit_order(self, payload: dict[str, Any]) -> ExchangeOrderResult:
        """Submete a ordem à exchange e retorna o resultado."""
        ...

    def cancel_order(
        self, symbol: str, order_id: str | None, client_order_id: str | None
    ) -> ExchangeOrderResult:
        """Cancela uma ordem existente na exchange."""
        ...

    def fetch_order(
        self, symbol: str, order_id: str | None, client_order_id: str | None
    ) -> ExchangeOrderResult | None:
        """Consulta o estado atual de uma ordem na exchange."""
        ...


class FakeExchangeOrderAdapter:
    """Adapter simulado em memória para testes determinísticos sem rede."""

    def __init__(
        self,
        default_status: OrderStatus = OrderStatus.ACKNOWLEDGED,
        simulate_timeout: bool = False,
        simulate_reject: bool = False,
        reject_reason: str = "Fake exchange rejection",
        environment: BinanceEnvironment | None = None,
        balances: dict[str, dict[str, Decimal]] | None = None,
        ticker_price: float = 60000.0,
    ) -> None:
        self.default_status = default_status
        self.simulate_timeout = simulate_timeout
        self.simulate_reject = simulate_reject
        self.reject_reason = reject_reason
        self.environment = environment
        self.ticker_price = ticker_price
        self.submitted_payloads: list[dict[str, Any]] = []
        self.canceled_requests: list[dict[str, Any]] = []
        self.orders: dict[str, ExchangeOrderResult] = {}
        self._next_id = 1000
        self._balances = balances or {
            "USDT": {"free": Decimal("10000.00"), "used": Decimal("0.00"), "total": Decimal("10000.00")},
            "BTC": {"free": Decimal("0.00010000"), "used": Decimal("0.00"), "total": Decimal("0.00010000")},
        }

    def submit_order(self, payload: dict[str, Any]) -> ExchangeOrderResult:
        self.submitted_payloads.append(payload)
        client_order_id = payload["params"]["clientOrderId"]

        if self.simulate_timeout:
            raise TimeoutError("Simulated network timeout during order submission.")

        now_iso = datetime.now(timezone.utc).isoformat()
        qty = Decimal(str(payload["amount"]))
        px = Decimal(str(payload["price"])) if "price" in payload else None

        if self.simulate_reject:
            res = ExchangeOrderResult(
                client_order_id=client_order_id,
                exchange_order_id=None,
                status=OrderStatus.REJECTED,
                symbol=payload["symbol"],
                side=payload["side"].upper(),
                order_type=payload["type"].upper(),
                requested_quantity=qty,
                executed_quantity=Decimal("0"),
                cumulative_quote_quantity=Decimal("0"),
                average_price=None,
                created_at=now_iso,
                updated_at=now_iso,
                raw_response={"status": "REJECTED", "reason": self.reject_reason},
            )
            self.orders[client_order_id] = res
            return res

        self._next_id += 1
        exchange_order_id = f"fake_exch_{self._next_id}"

        # Se default_status for FILLED, simula execução completa
        exec_qty = qty if self.default_status == OrderStatus.FILLED else Decimal("0")
        cum_quote = (qty * (px or Decimal("50000.00"))) if self.default_status == OrderStatus.FILLED else Decimal("0")

        res = ExchangeOrderResult(
            client_order_id=client_order_id,
            exchange_order_id=exchange_order_id,
            status=self.default_status,
            symbol=payload["symbol"],
            side=payload["side"].upper(),
            order_type=payload["type"].upper(),
            requested_quantity=qty,
            executed_quantity=exec_qty,
            cumulative_quote_quantity=cum_quote,
            average_price=px,
            created_at=now_iso,
            updated_at=now_iso,
            raw_response={"status": self.default_status.value, "orderId": exchange_order_id},
        )
        self.orders[client_order_id] = res
        return res

    def cancel_order(
        self, symbol: str, order_id: str | None, client_order_id: str | None
    ) -> ExchangeOrderResult:
        key = client_order_id or order_id or ""
        self.canceled_requests.append({"symbol": symbol, "order_id": order_id, "client_order_id": client_order_id})
        existing = self.orders.get(key)
        now_iso = datetime.now(timezone.utc).isoformat()
        if existing:
            canceled = ExchangeOrderResult(
                client_order_id=existing.client_order_id,
                exchange_order_id=existing.exchange_order_id,
                status=OrderStatus.CANCELED,
                symbol=existing.symbol,
                side=existing.side,
                order_type=existing.order_type,
                requested_quantity=existing.requested_quantity,
                executed_quantity=existing.executed_quantity,
                cumulative_quote_quantity=existing.cumulative_quote_quantity,
                average_price=existing.average_price,
                created_at=existing.created_at,
                updated_at=now_iso,
                raw_response={"status": "CANCELED"},
            )
            self.orders[key] = canceled
            return canceled

        return ExchangeOrderResult(
            client_order_id=client_order_id or "unknown",
            exchange_order_id=order_id,
            status=OrderStatus.CANCELED,
            symbol=symbol,
            side="UNKNOWN",
            order_type="UNKNOWN",
            requested_quantity=Decimal("0"),
            executed_quantity=Decimal("0"),
            cumulative_quote_quantity=Decimal("0"),
            average_price=None,
            created_at=now_iso,
            updated_at=now_iso,
        )

    def fetch_order(
        self, symbol: str, order_id: str | None, client_order_id: str | None
    ) -> ExchangeOrderResult | None:
        key = client_order_id or order_id or ""
        return self.orders.get(key)

    def fetch_ticker(self, symbol: str) -> dict[str, Any]:
        """Retorna ticker simulado para testes sem rede."""
        return {
            "symbol": symbol,
            "last": self.ticker_price,
            "ask": self.ticker_price,
            "bid": self.ticker_price,
            "close": self.ticker_price,
        }

    def set_balance(self, asset: str, free: Decimal, used: Decimal = Decimal("0.00")) -> None:
        """Define saldo simulado de um ativo para testes."""
        self._balances[asset] = {
            "free": free,
            "used": used,
            "total": free + used,
        }

    def get_balances(self) -> dict[str, dict[str, Decimal]]:
        """Retorna saldos simulados para testes sem rede."""
        return dict(self._balances)

    def load_markets(self) -> dict[str, Any]:
        """Retorna metadados simulados de BTC/USDT para testes sem rede."""
        return {
            "BTC/USDT": {
                "symbol": "BTC/USDT",
                "limits": {
                    "amount": {"min": 0.00001, "max": 9000.0},
                    "price": {"min": 0.01, "max": 1000000.0},
                    "cost": {"min": 5.0, "max": None},
                },
                "precision": {
                    "amount": 0.00001,
                    "price": 0.01,
                },
            }
        }


class BinanceOrderAdapter:
    """Adapter para a Binance Private Exchange com barreira de segurança estrita da FASE 8.4B."""

    def __init__(
        self,
        private_exchange: BinancePrivateExchange | None = None,
        real_order_submission_enabled: bool = False,
    ) -> None:
        self.private_exchange = private_exchange
        self.real_order_submission_enabled = real_order_submission_enabled
        self.environment: BinanceEnvironment = BinanceEnvironment.PRODUCTION

    def submit_order(self, payload: dict[str, Any]) -> ExchangeOrderResult:
        """Barreira de segurança incondicional da FASE 8.4B: ordens reais são bloqueadas."""
        if not self.real_order_submission_enabled:
            raise RealOrderSubmissionBlockedError(
                "CRITICAL: Submissão real de ordens Binance bloqueada na FASE 8.4B. "
                "A primeira operação financeira real fica restrita à FASE 8.4C assistida."
            )
        # Se um dia habilitado em fases futuras, private_exchange continua protegido por suas próprias barreiras
        if self.private_exchange is not None:
            self.private_exchange.create_order(
                payload["symbol"],
                payload["type"],
                payload["side"],
                payload["amount"],
                payload.get("price"),
                payload.get("params"),
            )
        raise RealOrderSubmissionBlockedError("Bloqueio final incondicional de ordens na Fase 8.4B.")

    def cancel_order(
        self, symbol: str, order_id: str | None, client_order_id: str | None
    ) -> ExchangeOrderResult:
        """Barreira de segurança incondicional da FASE 8.4B: cancelamentos reais são bloqueados."""
        if not self.real_order_submission_enabled:
            raise RealOrderSubmissionBlockedError(
                "CRITICAL: Cancelamento real de ordens Binance bloqueado na FASE 8.4B. "
                "A primeira operação financeira real fica restrita à FASE 8.4C assistida."
            )
        if self.private_exchange is not None:
            self.private_exchange.cancel_order(order_id or client_order_id, symbol)
        raise RealOrderSubmissionBlockedError("Bloqueio final incondicional de cancelamento na Fase 8.4B.")

    def fetch_order(
        self, symbol: str, order_id: str | None, client_order_id: str | None
    ) -> ExchangeOrderResult | None:
        raise RealOrderSubmissionBlockedError(
            "CRITICAL: Consulta real de ordens Binance bloqueada na FASE 8.4B."
        )


class LiveOrderStorage:
    """Armazenamento local SQLite e rastreamento auditável de lifecycle de ordens live."""

    def __init__(self, db_path: Path | str = "data/live_orders.sqlite3") -> None:
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS live_orders (
                    correlation_id TEXT PRIMARY KEY,
                    client_order_id TEXT NOT NULL UNIQUE,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    order_type TEXT NOT NULL,
                    requested_quantity TEXT NOT NULL,
                    requested_notional TEXT NOT NULL,
                    current_status TEXT NOT NULL,
                    exchange_order_id TEXT,
                    executed_quantity TEXT NOT NULL,
                    cumulative_quote_quantity TEXT NOT NULL,
                    average_price TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS live_order_lifecycle (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    correlation_id TEXT NOT NULL,
                    client_order_id TEXT NOT NULL,
                    previous_status TEXT,
                    new_status TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    details_json TEXT
                )
                """
            )
            conn.commit()
        finally:
            if self.db_path != ":memory:":
                conn.close()

    def record_transition(self, record: OrderLifecycleRecord) -> None:
        """Registra append-only a transição de estado no lifecycle e atualiza a tabela live_orders."""
        conn = self._get_connection()
        try:
            conn.execute(
                """
                INSERT INTO live_order_lifecycle (
                    correlation_id, client_order_id, previous_status,
                    new_status, timestamp, reason, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.correlation_id,
                    record.client_order_id,
                    record.previous_status.value if record.previous_status else None,
                    record.new_status.value,
                    record.timestamp,
                    record.reason,
                    json.dumps(record.details) if record.details else None,
                ),
            )
            conn.commit()
        finally:
            if self.db_path != ":memory:":
                conn.close()

    def save_initial_order(
        self,
        correlation_id: str,
        client_order_id: str,
        symbol: str,
        side: str,
        order_type: str,
        requested_quantity: Decimal,
        requested_notional: Decimal,
        status: OrderStatus,
        created_at: str,
    ) -> None:
        conn = self._get_connection()
        try:
            conn.execute(
                """
                INSERT INTO live_orders (
                    correlation_id, client_order_id, symbol, side, order_type,
                    requested_quantity, requested_notional, current_status,
                    exchange_order_id, executed_quantity, cumulative_quote_quantity,
                    average_price, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    correlation_id,
                    client_order_id,
                    symbol,
                    side,
                    order_type,
                    str(requested_quantity),
                    str(requested_notional),
                    status.value,
                    None,
                    "0",
                    "0",
                    None,
                    created_at,
                    created_at,
                ),
            )
            conn.commit()
        finally:
            if self.db_path != ":memory:":
                conn.close()

    def update_order_status(
        self,
        client_order_id: str,
        status: OrderStatus,
        updated_at: str,
        exchange_order_id: str | None = None,
        executed_quantity: Decimal | None = None,
        cumulative_quote_quantity: Decimal | None = None,
        average_price: Decimal | None = None,
    ) -> None:
        conn = self._get_connection()
        try:
            conn.execute(
                """
                UPDATE live_orders
                SET current_status = ?,
                    exchange_order_id = COALESCE(?, exchange_order_id),
                    executed_quantity = COALESCE(?, executed_quantity),
                    cumulative_quote_quantity = COALESCE(?, cumulative_quote_quantity),
                    average_price = COALESCE(?, average_price),
                    updated_at = ?
                WHERE client_order_id = ?
                """,
                (
                    status.value,
                    exchange_order_id,
                    str(executed_quantity) if executed_quantity is not None else None,
                    str(cumulative_quote_quantity) if cumulative_quote_quantity is not None else None,
                    str(average_price) if average_price is not None else None,
                    updated_at,
                    client_order_id,
                ),
            )
            conn.commit()
        finally:
            if self.db_path != ":memory:":
                conn.close()

    def get_order_by_correlation_id(self, correlation_id: str) -> dict[str, Any] | None:
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM live_orders WHERE correlation_id = ?",
                (correlation_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            if self.db_path != ":memory:":
                conn.close()

    def get_order_by_client_order_id(self, client_order_id: str) -> dict[str, Any] | None:
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM live_orders WHERE client_order_id = ?",
                (client_order_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            if self.db_path != ":memory:":
                conn.close()

    def get_lifecycle_history(self, correlation_id: str) -> list[OrderLifecycleRecord]:
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                """
                SELECT * FROM live_order_lifecycle
                WHERE correlation_id = ?
                ORDER BY id ASC
                """,
                (correlation_id,),
            )
            records = []
            for row in cursor.fetchall():
                prev_st = OrderStatus(row["previous_status"]) if row["previous_status"] else None
                new_st = OrderStatus(row["new_status"])
                records.append(
                    OrderLifecycleRecord(
                        correlation_id=row["correlation_id"],
                        client_order_id=row["client_order_id"],
                        previous_status=prev_st,
                        new_status=new_st,
                        timestamp=row["timestamp"],
                        reason=row["reason"],
                        details=json.loads(row["details_json"]) if row["details_json"] else None,
                    )
                )
            return records
        finally:
            if self.db_path != ":memory:":
                conn.close()

    def close(self) -> None:
        if self._memory_conn is not None:
            self._memory_conn.close()
            self._memory_conn = None


class GuardedLiveExecutionEngine:
    """Motor de execução LIVE protegido e defensivo.

    Aceita EXCLUSIVAMENTE ApprovedOrderIntent.
    Exige injeção explícita de adapter da exchange.
    Implementa Triple Arming, Micro-Order Cap, Idempotência e Tratamento de Falha Ambígua.
    """

    def __init__(
        self,
        adapter: ExchangeOrderAdapter,
        storage: LiveOrderStorage | None = None,
        config: Config | None = None,
    ) -> None:
        if adapter is None:
            raise ValueError("Um adapter de exchange deve ser explicitamente fornecido ao GuardedLiveExecutionEngine.")
        self.adapter = adapter
        self.storage = storage or LiveOrderStorage(":memory:")
        self.config = config or Config()

    def execute(self, approved_intent: ApprovedOrderIntent) -> ExchangeOrderResult:
        """Executa a intenção de ordem aprovada com salvaguardas live rigorosas."""
        # 1. Validação de tipo estrutural
        if not isinstance(approved_intent, ApprovedOrderIntent):
            raise InvalidExecutionIntentError(
                f"GuardedLiveExecutionEngine aceita apenas ApprovedOrderIntent. Recebido: {type(approved_intent).__name__}"
            )

        # 2. Environment Sentry & Independent Arming
        if self.config.binance_environment == BinanceEnvironment.SPOT_TESTNET:
            if not self.config.testnet_execution_enabled:
                raise LiveExecutionArmingError(
                    "testnet_execution_enabled é False. Execução em Binance Spot Testnet está desarmada por padrão."
                )
            if isinstance(self.adapter, BinanceOrderAdapter):
                raise RuntimeError(
                    "Environment mismatch: BinanceOrderAdapter (produção) não pode ser usado em ambiente SPOT_TESTNET."
                )
            adapter_env = getattr(self.adapter, "environment", None)
            if adapter_env is not None and adapter_env != BinanceEnvironment.SPOT_TESTNET:
                raise RuntimeError(
                    f"Environment mismatch: Adapter configurado para ambiente '{adapter_env}', "
                    f"mas engine está operando em '{self.config.binance_environment}'."
                )
        else:
            # PRODUÇÃO (DEFAULT SEGURO)
            if self.config.trading_mode != "live":
                raise LiveExecutionArmingError(
                    f"trading_mode deve ser 'live' para execução live em produção. Modo atual: '{self.config.trading_mode}'."
                )
            if not self.config.live_trading_acknowledged:
                raise LiveExecutionArmingError(
                    "live_trading_acknowledged é False. Autorização explícita do operador é mandatória para produção."
                )
            if not self.config.live_execution_enabled:
                raise LiveExecutionArmingError(
                    "live_execution_enabled é False. Execução live em produção está desarmada por padrão."
                )
            adapter_env = getattr(self.adapter, "environment", None)
            if adapter_env is not None and adapter_env != BinanceEnvironment.PRODUCTION:
                raise RuntimeError(
                    f"Environment mismatch: Adapter configurado para ambiente '{adapter_env}', "
                    f"mas engine está operando em '{self.config.binance_environment}'."
                )

        # 3. Verificação do Micro-Order Cap (Teto de Micro-Ordem)
        cap = Decimal(str(self.config.live_micro_order_max_notional))
        notional = approved_intent.normalized_notional
        req_notional = approved_intent.intent.requested_notional
        if notional > cap or req_notional > cap:
            raise MicroOrderCapExceededError(
                f"Notional ({notional} USDT) excede o teto de micro-ordem permitido ({cap} USDT). "
                f"A ordem NÃO é reduzida automaticamente."
            )

        correlation_id = approved_intent.intent.correlation_id
        client_order_id = generate_client_order_id(correlation_id)

        # 4. Verificação de Idempotência
        existing = self.storage.get_order_by_correlation_id(correlation_id)
        if existing is not None:
            raise RuntimeError(
                f"DUPLICATE_INTENT: Ordem com correlation_id '{correlation_id}' já registrada com status '{existing['current_status']}'."
            )

        # 5. Inicialização do Ciclo de Vida: PREPARED -> PENDING_SUBMISSION
        now_iso = datetime.now(timezone.utc).isoformat()
        self.storage.save_initial_order(
            correlation_id=correlation_id,
            client_order_id=client_order_id,
            symbol=approved_intent.intent.symbol,
            side=approved_intent.intent.side,
            order_type=approved_intent.intent.order_type,
            requested_quantity=approved_intent.normalized_quantity,
            requested_notional=approved_intent.normalized_notional,
            status=OrderStatus.PENDING_SUBMISSION,
            created_at=now_iso,
        )
        self.storage.record_transition(
            OrderLifecycleRecord(
                correlation_id=correlation_id,
                client_order_id=client_order_id,
                previous_status=OrderStatus.PREPARED,
                new_status=OrderStatus.PENDING_SUBMISSION,
                timestamp=now_iso,
                reason="Intenção aprovada registrada para submissão.",
            )
        )

        # 6. Construção do Payload Canônico
        payload = build_order_payload(approved_intent, client_order_id)

        # 7. Submissão ao Adapter com Tratamento Estrito de Falha Ambígua
        try:
            result = self.adapter.submit_order(payload)
            update_time = datetime.now(timezone.utc).isoformat()
            self.storage.update_order_status(
                client_order_id=client_order_id,
                status=result.status,
                updated_at=update_time,
                exchange_order_id=result.exchange_order_id,
                executed_quantity=result.executed_quantity,
                cumulative_quote_quantity=result.cumulative_quote_quantity,
                average_price=result.average_price,
            )
            self.storage.record_transition(
                OrderLifecycleRecord(
                    correlation_id=correlation_id,
                    client_order_id=client_order_id,
                    previous_status=OrderStatus.PENDING_SUBMISSION,
                    new_status=result.status,
                    timestamp=update_time,
                    reason=f"Resposta da exchange recebida com status '{result.status.value}'.",
                )
            )
            return result

        except RealOrderSubmissionBlockedError:
            raise
        except (LiveExecutionArmingError, MicroOrderCapExceededError, InvalidExecutionIntentError):
            raise
        except Exception as exc:
            # REGRA CONSTITUCIONAL: UNKNOWN != FAILED e TIMEOUT != SAFE TO RETRY
            update_time = datetime.now(timezone.utc).isoformat()
            self.storage.update_order_status(
                client_order_id=client_order_id,
                status=OrderStatus.UNKNOWN,
                updated_at=update_time,
            )
            self.storage.record_transition(
                OrderLifecycleRecord(
                    correlation_id=correlation_id,
                    client_order_id=client_order_id,
                    previous_status=OrderStatus.PENDING_SUBMISSION,
                    new_status=OrderStatus.UNKNOWN,
                    timestamp=update_time,
                    reason=f"Falha de rede/timeout durante envio ({type(exc).__name__}: {exc}). Estado ambíguo; auto-retry PROIBIDO.",
                    details={"error": str(exc)},
                )
            )
            return ExchangeOrderResult(
                client_order_id=client_order_id,
                exchange_order_id=None,
                status=OrderStatus.UNKNOWN,
                symbol=approved_intent.intent.symbol,
                side=approved_intent.intent.side,
                order_type=approved_intent.intent.order_type,
                requested_quantity=approved_intent.normalized_quantity,
                executed_quantity=Decimal("0"),
                cumulative_quote_quantity=Decimal("0"),
                average_price=None,
                created_at=now_iso,
                updated_at=update_time,
                raw_response={"error": str(exc)},
            )

    def reconcile_order(self, client_order_id: str) -> ExchangeOrderResult:
        """Reconcilia uma ordem com a exchange utilizando o clientOrderId determinístico.

        OBRIGATÓRIO para ordens em estado UNKNOWN antes de qualquer decisão.
        """
        order_dict = self.storage.get_order_by_client_order_id(client_order_id)
        if not order_dict:
            raise ValueError(f"Ordem com client_order_id '{client_order_id}' não encontrada no armazenamento local.")

        correlation_id = order_dict["correlation_id"]
        previous_status = OrderStatus(order_dict["current_status"])

        fetched = self.adapter.fetch_order(
            symbol=order_dict["symbol"],
            order_id=order_dict.get("exchange_order_id"),
            client_order_id=client_order_id,
        )

        now_iso = datetime.now(timezone.utc).isoformat()

        if fetched is not None:
            # Ordem confirmada na exchange: atualiza para o estado real
            self.storage.update_order_status(
                client_order_id=client_order_id,
                status=fetched.status,
                updated_at=now_iso,
                exchange_order_id=fetched.exchange_order_id,
                executed_quantity=fetched.executed_quantity,
                cumulative_quote_quantity=fetched.cumulative_quote_quantity,
                average_price=fetched.average_price,
            )
            self.storage.record_transition(
                OrderLifecycleRecord(
                    correlation_id=correlation_id,
                    client_order_id=client_order_id,
                    previous_status=previous_status,
                    new_status=fetched.status,
                    timestamp=now_iso,
                    reason=f"Reconciliação confirmada via fetch_order. Novo status: '{fetched.status.value}'.",
                )
            )
            return fetched

        # Ordem não encontrada na exchange após consulta
        self.storage.update_order_status(
            client_order_id=client_order_id,
            status=OrderStatus.REJECTED,
            updated_at=now_iso,
        )
        self.storage.record_transition(
            OrderLifecycleRecord(
                correlation_id=correlation_id,
                client_order_id=client_order_id,
                previous_status=previous_status,
                new_status=OrderStatus.REJECTED,
                timestamp=now_iso,
                reason="Ordem não encontrada na exchange durante reconciliação. Exige intervenção manual; auto-retry PROIBIDO.",
            )
        )
        return ExchangeOrderResult(
            client_order_id=client_order_id,
            exchange_order_id=None,
            status=OrderStatus.REJECTED,
            symbol=order_dict["symbol"],
            side=order_dict["side"],
            order_type=order_dict["order_type"],
            requested_quantity=Decimal(order_dict["requested_quantity"]),
            executed_quantity=Decimal("0"),
            cumulative_quote_quantity=Decimal("0"),
            average_price=None,
            created_at=order_dict["created_at"],
            updated_at=now_iso,
            raw_response={"reconcile": "NOT_FOUND_ON_EXCHANGE"},
        )

    def cancel_order(self, client_order_id: str) -> ExchangeOrderResult:
        """Cancela uma ordem aberta na exchange com salvaguardas de ciclo de vida."""
        order_dict = self.storage.get_order_by_client_order_id(client_order_id)
        if not order_dict:
            raise ValueError(f"Ordem com client_order_id '{client_order_id}' não encontrada no armazenamento local.")

        correlation_id = order_dict["correlation_id"]
        current_status = OrderStatus(order_dict["current_status"])

        # Ordem em estado UNKNOWN exige reconciliação prévia
        if current_status == OrderStatus.UNKNOWN:
            raise OrderNotCancelableError(
                f"Ordem '{client_order_id}' está em estado UNKNOWN. É obrigatório reconciliar antes de cancelar."
            )

        # Estados finais não podem ser cancelados
        if current_status in (OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED):
            raise OrderNotCancelableError(
                f"Ordem '{client_order_id}' já está em estado final '{current_status.value}' e não pode ser cancelada."
            )

        # Transição: CANCEL_PENDING
        pending_time = datetime.now(timezone.utc).isoformat()
        self.storage.update_order_status(
            client_order_id=client_order_id,
            status=OrderStatus.CANCEL_PENDING,
            updated_at=pending_time,
        )
        self.storage.record_transition(
            OrderLifecycleRecord(
                correlation_id=correlation_id,
                client_order_id=client_order_id,
                previous_status=current_status,
                new_status=OrderStatus.CANCEL_PENDING,
                timestamp=pending_time,
                reason="Solicitação de cancelamento enviada.",
            )
        )

        # Execução do cancelamento no adapter
        cancel_res = self.adapter.cancel_order(
            symbol=order_dict["symbol"],
            order_id=order_dict.get("exchange_order_id"),
            client_order_id=client_order_id,
        )

        cancel_time = datetime.now(timezone.utc).isoformat()
        self.storage.update_order_status(
            client_order_id=client_order_id,
            status=OrderStatus.CANCELED,
            updated_at=cancel_time,
        )
        self.storage.record_transition(
            OrderLifecycleRecord(
                correlation_id=correlation_id,
                client_order_id=client_order_id,
                previous_status=OrderStatus.CANCEL_PENDING,
                new_status=OrderStatus.CANCELED,
                timestamp=cancel_time,
                reason="Cancelamento confirmado pela exchange.",
            )
        )

        return cancel_res
