"""Módulo de execução de ordens em modo DRY-RUN — FASE 8.4A.

Este módulo implementa o pipeline de execução simulada (Dry-Run), que aceita
exclusivamente instâncias de ApprovedOrderIntent e produz DryRunOrderResult.

REGRAS CONSTITUCIONAIS:
- ZERO REAL ORDERS: Nenhuma ordem real é submetida.
- APPROVED INTENT != REAL ORDER: O engine valida a geração de payload e idempotência.
- DRY_RUN != PAPER TRADING: Paper Trading simula patrimônio/posições contínuas ao longo do tempo;
  Dry-Run valida o pipeline operacional de submissão sem preenchimento financeiro nem alteração patrimonial.
- FAIL-CLOSED: Qualquer entrada não aprovada, modo LIVE ou erro de persistência
  bloqueia a execução imediatamente.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
import hashlib
from pathlib import Path
import sqlite3
from typing import Any

from finbot.config import Config
from finbot.live_safety import (
    AccountStateSnapshot,
    ApprovedOrderIntent,
    LiveSafetyGate,
    MarketFilterGuard,
    OrderIntent,
    SafetyDecision,
)
from finbot.risk import RiskDecision


class ExecutionMode(str, Enum):
    """Modos de execução suportados pelo FinBot."""

    DRY_RUN = "DRY_RUN"
    LIVE = "LIVE"


class LiveExecutionBlockedError(RuntimeError):
    """Lançado se qualquer tentativa de execução LIVE for solicitada nesta fase."""

    pass


class InvalidExecutionIntentError(TypeError):
    """Lançado se uma intenção que não seja ApprovedOrderIntent for submetida ao engine."""

    pass


def generate_client_order_id(correlation_id: str) -> str:
    """Gera um clientOrderId determinístico compatível com as regras da Binance Spot.

    Regras da Binance Spot para newClientOrderId:
    - Comprimento máximo: 36 caracteres.
    - Caracteres permitidos: letras, dígitos, sublinhado e hífen.
    - Não expõe segredos ou identificadores sensíveis.
    - Determinístico: mesmo correlation_id sempre produz exatamente o mesmo clientOrderId.
    """
    if not correlation_id or not isinstance(correlation_id, str) or not correlation_id.strip():
        raise ValueError("correlation_id deve ser uma string não vazia.")

    # Prefixo oficial de rastreabilidade do FinBot
    prefix = "finbot_"  # 7 caracteres
    # Gera um hash SHA-256 do correlation_id e usa os primeiros 28 caracteres hexadecimais
    # Total de caracteres: 7 + 28 = 35 caracteres (respeita o limite <= 36 da Binance)
    hash_part = hashlib.sha256(correlation_id.strip().encode("utf-8")).hexdigest()[:28]
    return f"{prefix}{hash_part}"


def build_order_payload(
    approved_intent: ApprovedOrderIntent,
    client_order_id: str,
) -> dict[str, Any]:
    """Constrói o payload canônico para submissão à exchange (sem executar chamada HTTP).

    Consome exclusivamente ApprovedOrderIntent e clientOrderId.
    Não conhece API Keys, Secrets ou credenciais.
    """
    if not isinstance(approved_intent, ApprovedOrderIntent):
        raise InvalidExecutionIntentError(
            f"approved_intent deve ser uma instância de ApprovedOrderIntent. Recebido: {type(approved_intent).__name__}"
        )

    if not client_order_id or not isinstance(client_order_id, str) or not client_order_id.strip():
        raise ValueError("client_order_id deve ser uma string não vazia.")

    intent = approved_intent.intent

    payload: dict[str, Any] = {
        "symbol": intent.symbol,
        "type": intent.order_type.lower(),
        "side": intent.side.lower(),
        "amount": float(approved_intent.normalized_quantity),
        "params": {
            "clientOrderId": client_order_id,
        },
    }

    if approved_intent.normalized_price is not None:
        payload["price"] = float(approved_intent.normalized_price)

    return payload


@dataclass(frozen=True)
class DryRunOrderResult:
    """Resultado imutável de uma execução simulada em modo Dry-Run."""

    correlation_id: str
    client_order_id: str
    symbol: str
    side: str
    order_type: str
    quantity: Decimal
    price: Decimal | None
    notional: Decimal
    status: str  # "SIMULATED_ACCEPTED", "DUPLICATE_INTENT", etc.
    created_at: str
    safety_reason: str
    execution_mode: str = ExecutionMode.DRY_RUN.value
    order_payload: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.execution_mode != ExecutionMode.DRY_RUN.value:
            raise ValueError(f"execution_mode deve ser estritamente DRY_RUN, obtido: {self.execution_mode}")
        if self.status == "FILLED":
            raise ValueError("status 'FILLED' é expressamente proibido em modo Dry-Run.")


class DryRunStorage:
    """Armazenamento local SQLite e mecanismo de idempotência para execuções Dry-Run."""

    def __init__(self, db_path: Path | str = "data/dry_run_orders.sqlite3") -> None:
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
                CREATE TABLE IF NOT EXISTS dry_run_orders (
                    correlation_id TEXT PRIMARY KEY,
                    client_order_id TEXT NOT NULL UNIQUE,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    order_type TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    price TEXT,
                    notional TEXT NOT NULL,
                    execution_mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    safety_reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()
        finally:
            if self.db_path != ":memory:":
                conn.close()

    def get_by_correlation_id(self, correlation_id: str) -> DryRunOrderResult | None:
        """Recupera uma execução prévia pelo correlation_id."""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM dry_run_orders WHERE correlation_id = ?",
                (correlation_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return self._row_to_result(row)
        finally:
            if self.db_path != ":memory:":
                conn.close()

    def get_by_client_order_id(self, client_order_id: str) -> DryRunOrderResult | None:
        """Recupera uma execução prévia pelo client_order_id."""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM dry_run_orders WHERE client_order_id = ?",
                (client_order_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return self._row_to_result(row)
        finally:
            if self.db_path != ":memory:":
                conn.close()

    def save_order(self, order: DryRunOrderResult) -> None:
        """Persiste uma execução Dry-Run de forma append-only."""
        conn = self._get_connection()
        try:
            conn.execute(
                """
                INSERT INTO dry_run_orders (
                    correlation_id,
                    client_order_id,
                    symbol,
                    side,
                    order_type,
                    quantity,
                    price,
                    notional,
                    execution_mode,
                    status,
                    safety_reason,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order.correlation_id,
                    order.client_order_id,
                    order.symbol,
                    order.side,
                    order.order_type,
                    str(order.quantity),
                    str(order.price) if order.price is not None else None,
                    str(order.notional),
                    order.execution_mode,
                    order.status,
                    order.safety_reason,
                    order.created_at,
                ),
            )
            conn.commit()
        finally:
            if self.db_path != ":memory:":
                conn.close()

    def close(self) -> None:
        """Fecha conexão em memória se aplicável."""
        if self._memory_conn is not None:
            self._memory_conn.close()
            self._memory_conn = None

    @staticmethod
    def _row_to_result(row: sqlite3.Row) -> DryRunOrderResult:
        return DryRunOrderResult(
            correlation_id=row["correlation_id"],
            client_order_id=row["client_order_id"],
            symbol=row["symbol"],
            side=row["side"],
            order_type=row["order_type"],
            quantity=Decimal(row["quantity"]),
            price=Decimal(row["price"]) if row["price"] is not None else None,
            notional=Decimal(row["notional"]),
            execution_mode=row["execution_mode"],
            status=row["status"],
            safety_reason=row["safety_reason"],
            created_at=row["created_at"],
            order_payload=None,
        )


class DryRunExecutionEngine:
    """Motor de execução em modo Dry-Run.

    Processa exclusivamente instâncias de ApprovedOrderIntent sob o modo DRY_RUN.
    """

    def __init__(
        self,
        mode: ExecutionMode = ExecutionMode.DRY_RUN,
        storage: DryRunStorage | None = None,
    ) -> None:
        if mode == ExecutionMode.LIVE:
            raise LiveExecutionBlockedError(
                "ExecutionMode.LIVE está estritamente bloqueado nesta fase do FinBot."
            )
        if mode != ExecutionMode.DRY_RUN:
            raise ValueError(f"Modo de execução não suportado: {mode}")

        self.mode = mode
        self.storage = storage or DryRunStorage(":memory:")

    def execute(self, approved_intent: ApprovedOrderIntent) -> DryRunOrderResult:
        """Executa a intenção de ordem em modo Dry-Run com garantia de idempotência.

        FAIL CLOSED:
        - Rejeita se approved_intent não for ApprovedOrderIntent.
        - Verifica duplicidade via correlation_id ou client_order_id.
        """
        if not isinstance(approved_intent, ApprovedOrderIntent):
            raise InvalidExecutionIntentError(
                f"DryRunExecutionEngine aceita apenas ApprovedOrderIntent. Recebido: {type(approved_intent).__name__}"
            )

        correlation_id = approved_intent.intent.correlation_id
        client_order_id = generate_client_order_id(correlation_id)

        # 1. Verificação de idempotência antes de qualquer processamento
        existing = self.storage.get_by_correlation_id(correlation_id)
        if existing is not None:
            return DryRunOrderResult(
                correlation_id=correlation_id,
                client_order_id=client_order_id,
                symbol=approved_intent.intent.symbol,
                side=approved_intent.intent.side,
                order_type=approved_intent.intent.order_type,
                quantity=approved_intent.normalized_quantity,
                price=approved_intent.normalized_price,
                notional=approved_intent.normalized_notional,
                status="DUPLICATE_INTENT",
                created_at=datetime.now(timezone.utc).isoformat(),
                safety_reason=f"Ordem duplicada ignorada (já registrada com status {existing.status}).",
                execution_mode=ExecutionMode.DRY_RUN.value,
                order_payload=None,
            )

        # 2. Construção do payload canônico da exchange
        payload = build_order_payload(approved_intent, client_order_id)
        now_iso = datetime.now(timezone.utc).isoformat()

        # 3. Criação do resultado simulado aceito
        result = DryRunOrderResult(
            correlation_id=correlation_id,
            client_order_id=client_order_id,
            symbol=approved_intent.intent.symbol,
            side=approved_intent.intent.side,
            order_type=approved_intent.intent.order_type,
            quantity=approved_intent.normalized_quantity,
            price=approved_intent.normalized_price,
            notional=approved_intent.normalized_notional,
            status="SIMULATED_ACCEPTED",
            created_at=now_iso,
            safety_reason="Aprovado por todos os gates de segurança.",
            execution_mode=ExecutionMode.DRY_RUN.value,
            order_payload=payload,
        )

        # 4. Persistência da execução no storage
        self.storage.save_order(result)

        return result


def run_dry_run_pipeline(
    intent: OrderIntent,
    gate: LiveSafetyGate,
    engine: DryRunExecutionEngine,
    risk_decision: RiskDecision | None,
    market_guard: MarketFilterGuard | None,
    account_snapshot: AccountStateSnapshot | None,
    config: Config,
) -> tuple[SafetyDecision, DryRunOrderResult | None]:
    """Orquestrador do pipeline de execução Dry-Run.

    OrderIntent -> LiveSafetyGate -> ApprovedOrderIntent -> DryRunExecutionEngine

    Se o gate rejeitar: o engine NUNCA é chamado.
    Se o gate aprovar: o engine gera o DryRunOrderResult.
    """
    decision = gate.evaluate(
        intent=intent,
        risk_decision=risk_decision,
        market_guard=market_guard,
        account_snapshot=account_snapshot,
        config=config,
    )

    if not decision.allowed or decision.approved_intent is None:
        return decision, None

    result = engine.execute(decision.approved_intent)
    return decision, result
