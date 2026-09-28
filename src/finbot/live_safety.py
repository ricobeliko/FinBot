"""Módulo de fundação defensiva de segurança para futura execução live (FASE 8.3).

Este módulo atua como a barreira preliminar, sanitizadora e regulatória entre
a decisão de risco gerada pelo Risk Engine e qualquer futura submissão à Binance Spot.

REGRAS CONSTITUCIONAIS DA FASE 8.3:
1. ESTA FASE NÃO EXECUTA ORDENS REAIS.
2. APPROVED INTENT != EXECUTED ORDER: Uma intenção aprovada não é despachada para a exchange.
3. FAIL-CLOSED: Qualquer dado ausente, inválido, NaN, infinito ou exceção resulta em rejeição.
4. SOBERANIA DO RISK ENGINE: O LiveSafetyGate consome a decisão do Risk Engine;
   se o Risk Engine rejeitar, o SafetyGate rejeita sumariamente (sem overrides ou bypass).
5. MARKET FILTER GUARD: Quantidades e preços são truncados estritamente pelo stepSize/tickSize.
   NUNCA aumenta silenciosamente uma ordem para atingir mínimo. Se estiver abaixo do mínimo -> REJECT.
6. HARD LIVE LIMIT: Limite financeiro máximo estrito (live_max_order_notional).
   Se requested_notional > live_max_order_notional -> REJECT (nunca trunca para caber).
7. LIVE ACKNOWLEDGEMENT: Exige trading_mode == 'live' E live_trading_acknowledged == True.
8. STATE RECONCILIATION: Reconciliação prévia com saldo da conta. Saldo insuficiente -> REJECT.
9. ACCOUNT STATUS / API PERMISSIONS: Os campos can_trade/can_withdraw de /api/v3/account
   representam o status da CONTA do usuário na Binance e NÃO as restrições da API Key específica.
   Portanto, NÃO devem ser usados como mecanismo de autorização da chave de API.
10. BLOQUEIO ARQUITETURAL: create_order e cancel_order permanecem levantando LiveTradingBlockedError.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Generator
import uuid

from finbot.config import Config
from finbot.risk import RiskDecision

logger = logging.getLogger(__name__)


# =============================================================================
# ESTRUTURA DE FILTROS DE MERCADO E FUNÇÕES PURAS DE SANITIZAÇÃO
# =============================================================================

@dataclass(frozen=True)
class MarketFilters:
    """Regras e filtros de negociação de um par de mercado Binance Spot extraídos do CCXT."""

    symbol: str
    base_asset: str
    quote_asset: str
    min_amount: Decimal
    max_amount: Decimal | None
    amount_step: Decimal
    min_price: Decimal
    max_price: Decimal | None
    price_step: Decimal
    min_cost: Decimal
    max_cost: Decimal | None


def _precision_to_step(prec: Any, default: Decimal) -> Decimal:
    """Converte precisão do CCXT (tick size ou número de casas decimais) para step Decimal."""
    if prec is None:
        return default
    if isinstance(prec, int) or (isinstance(prec, float) and prec.is_integer() and prec >= 1):
        return Decimal("10") ** (-int(prec))
    s = str(prec)
    try:
        val = Decimal(s)
        if val > 0:
            return val
        return default
    except Exception:
        return default


def extract_market_filters(market_data: dict[str, Any]) -> MarketFilters:
    """Extrai e normaliza regras de negociação de um dicionário de mercado do CCXT."""
    symbol = market_data.get("symbol", "")
    base = market_data.get("base", "")
    quote = market_data.get("quote", "")

    limits = market_data.get("limits") or {}
    precision = market_data.get("precision") or {}

    amount_limits = limits.get("amount") or {}
    min_amount_raw = amount_limits.get("min")
    max_amount_raw = amount_limits.get("max")

    price_limits = limits.get("price") or {}
    min_price_raw = price_limits.get("min")
    max_price_raw = price_limits.get("max")

    cost_limits = limits.get("cost") or {}
    min_cost_raw = cost_limits.get("min")
    max_cost_raw = cost_limits.get("max")

    amount_prec_raw = precision.get("amount")
    price_prec_raw = precision.get("price")

    # Fallback/refinamento através dos filtros brutos de info.filters se disponíveis
    raw_filters = market_data.get("info", {}).get("filters", [])
    for f in raw_filters:
        f_type = f.get("filterType")
        if f_type == "LOT_SIZE":
            if min_amount_raw is None:
                min_amount_raw = f.get("minQty")
            if max_amount_raw is None:
                max_amount_raw = f.get("maxQty")
            if amount_prec_raw is None:
                amount_prec_raw = f.get("stepSize")
        elif f_type == "PRICE_FILTER":
            if min_price_raw is None:
                min_price_raw = f.get("minPrice")
            if max_price_raw is None:
                max_price_raw = f.get("maxPrice")
            if price_prec_raw is None:
                price_prec_raw = f.get("tickSize")
        elif f_type in ("NOTIONAL", "MIN_NOTIONAL"):
            if min_cost_raw is None:
                min_cost_raw = f.get("minNotional")

    min_amount = Decimal(str(min_amount_raw)) if min_amount_raw is not None else Decimal("0.00001")
    max_amount = Decimal(str(max_amount_raw)) if max_amount_raw is not None else None
    amount_step = _precision_to_step(amount_prec_raw, default=Decimal("0.00001"))

    min_price = Decimal(str(min_price_raw)) if min_price_raw is not None else Decimal("0.01")
    max_price = Decimal(str(max_price_raw)) if max_price_raw is not None else None
    price_step = _precision_to_step(price_prec_raw, default=Decimal("0.01"))

    min_cost = Decimal(str(min_cost_raw)) if min_cost_raw is not None else Decimal("5.0")
    max_cost = Decimal(str(max_cost_raw)) if max_cost_raw is not None else None

    return MarketFilters(
        symbol=symbol,
        base_asset=base,
        quote_asset=quote,
        min_amount=min_amount,
        max_amount=max_amount,
        amount_step=amount_step,
        min_price=min_price,
        max_price=max_price,
        price_step=price_step,
        min_cost=min_cost,
        max_cost=max_cost,
    )


def sanitize_amount(
    amount: Decimal,
    min_amount: Decimal,
    amount_step: Decimal,
    max_amount: Decimal | None = None,
) -> tuple[bool, Decimal, str]:
    """Trunca o valor para múltiplos exatos de amount_step e valida limites.

    NUNCA aumenta a quantidade para atingir o mínimo. Se sanitizado < min -> REJECT.
    """
    if amount.is_nan() or amount.is_infinite() or amount <= 0:
        return False, Decimal("0"), "Quantidade deve ser um número positivo e finito."

    if amount_step <= 0:
        return False, Decimal("0"), "amount_step deve ser estritamente positivo."

    units = amount // amount_step
    sanitized = units * amount_step

    if sanitized < min_amount:
        return (
            False,
            sanitized,
            f"Quantidade sanitizada ({sanitized}) é inferior ao mínimo permitido ({min_amount}).",
        )

    if max_amount is not None and sanitized > max_amount:
        return (
            False,
            sanitized,
            f"Quantidade sanitizada ({sanitized}) excede o máximo permitido ({max_amount}).",
        )

    return True, sanitized, ""


def sanitize_price(
    price: Decimal,
    min_price: Decimal,
    price_step: Decimal,
    max_price: Decimal | None = None,
) -> tuple[bool, Decimal, str]:
    """Ajusta o preço para múltiplos exatos de price_step e valida limites."""
    if price.is_nan() or price.is_infinite() or price <= 0:
        return False, Decimal("0"), "Preço deve ser um número positivo e finito."

    if price_step <= 0:
        return False, Decimal("0"), "price_step deve ser estritamente positivo."

    units = price // price_step
    sanitized = units * price_step

    if sanitized < min_price:
        return (
            False,
            sanitized,
            f"Preço sanitizado ({sanitized}) é inferior ao mínimo permitido ({min_price}).",
        )

    if max_price is not None and sanitized > max_price:
        return (
            False,
            sanitized,
            f"Preço sanitizado ({sanitized}) excede o máximo permitido ({max_price}).",
        )

    return True, sanitized, ""


def validate_notional(
    notional: Decimal,
    min_cost: Decimal,
    max_cost: Decimal | None = None,
) -> tuple[bool, str]:
    """Valida se o valor financeiro da ordem (notional) atende às exigências da exchange."""
    if notional.is_nan() or notional.is_infinite() or notional <= 0:
        return False, "Notional deve ser um número positivo e finito."

    if notional < min_cost:
        return (
            False,
            f"Notional ({notional}) é inferior ao mínimo exigido pela exchange ({min_cost} USDT).",
        )

    if max_cost is not None and notional > max_cost:
        return (
            False,
            f"Notional ({notional}) excede o máximo permitido pela exchange ({max_cost} USDT).",
        )

    return True, ""


# =============================================================================
# ESTRUTURAS DE INTENÇÃO DE ORDEM (ORDER INTENT)
# =============================================================================

@dataclass(frozen=True)
class OrderIntent:
    """Representação imutável de uma intenção de ordem.

    IMPORTANTE: OrderIntent representa exclusivamente uma INTENÇÃO e NÃO pode enviar ordens.
    """

    symbol: str
    side: str  # "BUY" ou "SELL"
    order_type: str  # "MARKET" ou "LIMIT"
    quantity: Decimal
    price: Decimal | None
    requested_notional: Decimal
    strategy_name: str
    strategy_version: str
    signal: str
    created_at: str
    correlation_id: str

    def __post_init__(self) -> None:
        if self.side not in ("BUY", "SELL"):
            raise ValueError(f"Side inválido: {self.side}. Deve ser BUY ou SELL.")
        if self.order_type not in ("MARKET", "LIMIT"):
            raise ValueError(f"Order type inválido: {self.order_type}. Deve ser MARKET ou LIMIT.")
        if self.quantity <= 0 or self.quantity.is_nan() or self.quantity.is_infinite():
            raise ValueError("quantity deve ser estritamente positiva e finita.")
        if self.requested_notional <= 0 or self.requested_notional.is_nan() or self.requested_notional.is_infinite():
            raise ValueError("requested_notional deve ser estritamente positivo e finito.")
        if self.price is not None and (self.price <= 0 or self.price.is_nan() or self.price.is_infinite()):
            raise ValueError("price deve ser estritamente positivo e finito quando especificado.")


@dataclass(frozen=True)
class ApprovedOrderIntent:
    """Intenção de ordem aprovada após avaliação por todos os gates de segurança.

    NOTA: Uma intenção aprovada ainda NÃO constitui envio ou execução na exchange.
    """

    intent: OrderIntent
    normalized_quantity: Decimal
    normalized_price: Decimal | None
    normalized_notional: Decimal
    checks: dict[str, Any]
    approved_at: str


@dataclass(frozen=True)
class RejectedOrderIntent:
    """Intenção de ordem rejeitada por violação de regra de segurança."""

    intent: OrderIntent
    reason_code: str
    reason: str
    checks: dict[str, Any]
    rejected_at: str


@dataclass(frozen=True)
class FilterDecision:
    """Resultado da validação do MarketFilterGuard."""

    is_valid: bool
    code: str
    reason: str
    normalized_quantity: Decimal | None = None
    normalized_price: Decimal | None = None
    normalized_notional: Decimal | None = None


class MarketFilterGuard:
    """Guarda de filtros de mercado para validação e normalização de OrderIntent."""

    def __init__(self, filters: MarketFilters) -> None:
        self.filters = filters

    def validate_order_intent(self, intent: OrderIntent) -> FilterDecision:
        """Valida e normaliza uma OrderIntent contra os filtros de mercado da exchange."""
        # 1. Validação e sanitização da quantidade
        valid_amt, norm_amt, err_amt = sanitize_amount(
            amount=intent.quantity,
            min_amount=self.filters.min_amount,
            amount_step=self.filters.amount_step,
            max_amount=self.filters.max_amount,
        )
        if not valid_amt:
            return FilterDecision(
                is_valid=False,
                code="AMOUNT_FILTER_FAILED",
                reason=err_amt,
            )

        # 2. Validação e sanitização do preço (quando fornecido)
        norm_price: Decimal | None = None
        if intent.price is not None:
            valid_px, norm_price, err_px = sanitize_price(
                price=intent.price,
                min_price=self.filters.min_price,
                price_step=self.filters.price_step,
                max_price=self.filters.max_price,
            )
            if not valid_px:
                return FilterDecision(
                    is_valid=False,
                    code="PRICE_FILTER_FAILED",
                    reason=err_px,
                )
            calculated_notional = norm_amt * norm_price
        else:
            calculated_notional = intent.requested_notional

        # 3. Validação do valor nocional (cost)
        valid_notional, err_notional = validate_notional(
            notional=calculated_notional,
            min_cost=self.filters.min_cost,
            max_cost=self.filters.max_cost,
        )
        if not valid_notional:
            return FilterDecision(
                is_valid=False,
                code="NOTIONAL_FILTER_FAILED",
                reason=err_notional,
            )

        return FilterDecision(
            is_valid=True,
            code="PASSED",
            reason="Filtros de mercado aprovados.",
            normalized_quantity=norm_amt,
            normalized_price=norm_price,
            normalized_notional=calculated_notional,
        )


# =============================================================================
# RECONCILIAÇÃO DE ESTADO E SALDOS
# =============================================================================

@dataclass(frozen=True)
class AccountStateSnapshot:
    """Snapshot mínimo de saldos para reconciliação pré-ordem."""

    symbol: str
    base_asset: str  # ex: "BTC"
    quote_asset: str  # ex: "USDT"
    base_free: Decimal
    base_locked: Decimal
    quote_free: Decimal
    quote_locked: Decimal
    captured_at: str


@dataclass(frozen=True)
class ReconciliationDecision:
    """Resultado da reconciliação de saldo e posição."""

    is_valid: bool
    code: str
    reason: str


class StateReconciler:
    """Reconciliador de estado pré-ordem."""

    def reconcile(
        self,
        intent: OrderIntent,
        snapshot: AccountStateSnapshot | None,
        normalized_quantity: Decimal | None = None,
        normalized_notional: Decimal | None = None,
    ) -> ReconciliationDecision:
        """Verifica se há saldo suficiente para a execução da intenção."""
        if snapshot is None:
            return ReconciliationDecision(
                is_valid=False,
                code="ACCOUNT_SNAPSHOT_MISSING",
                reason="Snapshot do estado da conta ausente para reconciliação.",
            )

        if snapshot.symbol != intent.symbol:
            return ReconciliationDecision(
                is_valid=False,
                code="SYMBOL_MISMATCH",
                reason=f"Símbolo do snapshot ({snapshot.symbol}) diverge do intent ({intent.symbol}).",
            )

        if intent.side == "BUY":
            required_quote = normalized_notional or intent.requested_notional
            if snapshot.quote_free < required_quote:
                return ReconciliationDecision(
                    is_valid=False,
                    code="INSUFFICIENT_QUOTE_BALANCE",
                    reason=(
                        f"Saldo disponível de {snapshot.quote_asset} ({snapshot.quote_free}) "
                        f"é insuficiente para notional de {required_quote}."
                    ),
                )

        elif intent.side == "SELL":
            required_base = normalized_quantity or intent.quantity
            if snapshot.base_free < required_base:
                return ReconciliationDecision(
                    is_valid=False,
                    code="INSUFFICIENT_BASE_BALANCE",
                    reason=(
                        f"Saldo disponível de {snapshot.base_asset} ({snapshot.base_free}) "
                        f"é insuficiente para quantidade de {required_base}."
                    ),
                )

        return ReconciliationDecision(
            is_valid=True,
            code="PASSED",
            reason="Saldos reconciliados com sucesso.",
        )


# =============================================================================
# DECISÃO E GATE DE SEGURANÇA LIVE (LIVE SAFETY GATE)
# =============================================================================

@dataclass(frozen=True)
class SafetyDecision:
    """Resultado explícito e imutável emitido pelo LiveSafetyGate."""

    allowed: bool
    reason_code: str
    reason: str
    normalized_quantity: Decimal | None
    normalized_price: Decimal | None
    normalized_notional: Decimal | None
    checks: dict[str, Any]
    approved_intent: ApprovedOrderIntent | None = None
    rejected_intent: RejectedOrderIntent | None = None


class LiveSafetyGate:
    """Gate central de validação pré-execução para ordens live.

    Garante soberania do Risk Engine, conformidade de mercado, reconciliação de saldos,
    teto financeiro (hard limit) e autorização operacional explícita.
    """

    def __init__(self, audit_storage: LiveSafetyAuditStorage | None = None) -> None:
        self.audit_storage = audit_storage

    def evaluate(
        self,
        intent: OrderIntent,
        risk_decision: RiskDecision | None,
        market_guard: MarketFilterGuard | None,
        account_snapshot: AccountStateSnapshot | None,
        config: Config,
    ) -> SafetyDecision:
        """Avalia exaustivamente uma OrderIntent sob o princípio Fail-Closed."""
        checks: dict[str, Any] = {}
        now_iso = datetime.now(timezone.utc).isoformat()

        try:
            # 1. Verificação de integridade estrutural básica
            if not isinstance(intent, OrderIntent):
                return self._reject(
                    intent, "INVALID_INTENT", "intent deve ser uma instância de OrderIntent.", checks, now_iso
                )

            # 2. Soberania do Risk Engine (OBRIGATÓRIO: sem overrides)
            if risk_decision is None:
                return self._reject(
                    intent,
                    "RISK_DECISION_MISSING",
                    "Decisão do Risk Engine é mandatória e está ausente.",
                    checks,
                    now_iso,
                )

            if not risk_decision.allowed:
                return self._reject(
                    intent,
                    f"RISK_{risk_decision.code.value}",
                    f"Risk Engine rejeitou a operação: {risk_decision.reason}",
                    checks,
                    now_iso,
                )

            if risk_decision.action != intent.side:
                return self._reject(
                    intent,
                    "RISK_ACTION_MISMATCH",
                    f"Ação autorizada pelo Risk Engine ({risk_decision.action}) diverge da intenção ({intent.side}).",
                    checks,
                    now_iso,
                )
            checks["risk_engine"] = "PASSED"

            # 3. Verificação de Modo Live e Acknowledgement Explícito
            if config.trading_mode != "live":
                return self._reject(
                    intent,
                    "NOT_IN_LIVE_MODE",
                    f"Modo de trading configurado é '{config.trading_mode}'. LiveSafetyGate requer modo 'live'.",
                    checks,
                    now_iso,
                )

            if not config.live_trading_acknowledged:
                return self._reject(
                    intent,
                    "LIVE_NOT_ACKNOWLEDGED",
                    "Operação live não autorizada explicitamente pelo operador (live_trading_acknowledged=False).",
                    checks,
                    now_iso,
                )
            checks["acknowledgement"] = "PASSED"

            # 4. Verificação de Hard Live Limit (Teto Financeiro Estrito)
            hard_limit = Decimal(str(config.live_max_order_notional))
            if intent.requested_notional > hard_limit:
                return self._reject(
                    intent,
                    "HARD_LIVE_LIMIT_EXCEEDED",
                    (
                        f"Notional solicitado ({intent.requested_notional}) excede o teto operacional live "
                        f"configurado ({hard_limit} USDT). A ordem não é truncada automaticamente."
                    ),
                    checks,
                    now_iso,
                )
            checks["hard_live_limit"] = "PASSED"

            # 5. Verificação de Filtros de Mercado
            if market_guard is None:
                return self._reject(
                    intent,
                    "MARKET_GUARD_MISSING",
                    "MarketFilterGuard é obrigatório e está ausente.",
                    checks,
                    now_iso,
                )

            filter_dec = market_guard.validate_order_intent(intent)
            if not filter_dec.is_valid:
                return self._reject(
                    intent,
                    filter_dec.code,
                    f"Filtro de mercado rejeitado: {filter_dec.reason}",
                    checks,
                    now_iso,
                )
            checks["market_filters"] = "PASSED"

            # 6. Reconciliação de Estado e Saldos
            if account_snapshot is None:
                return self._reject(
                    intent,
                    "ACCOUNT_SNAPSHOT_MISSING",
                    "Snapshot da conta é obrigatório para reconciliação de saldo.",
                    checks,
                    now_iso,
                )

            reconciler = StateReconciler()
            recon_dec = reconciler.reconcile(
                intent=intent,
                snapshot=account_snapshot,
                normalized_quantity=filter_dec.normalized_quantity,
                normalized_notional=filter_dec.normalized_notional,
            )
            if not recon_dec.is_valid:
                return self._reject(
                    intent,
                    recon_dec.code,
                    f"Reconciliação de saldos falhou: {recon_dec.reason}",
                    checks,
                    now_iso,
                )
            checks["reconciliation"] = "PASSED"

            # 7. Aprovação Final
            checks["all_checks"] = "PASSED"
            approved = ApprovedOrderIntent(
                intent=intent,
                normalized_quantity=filter_dec.normalized_quantity or intent.quantity,
                normalized_price=filter_dec.normalized_price or intent.price,
                normalized_notional=filter_dec.normalized_notional or intent.requested_notional,
                checks=checks,
                approved_at=now_iso,
            )
            decision = SafetyDecision(
                allowed=True,
                reason_code="APPROVED",
                reason="OrderIntent aprovada pelo LiveSafetyGate para futura execução.",
                normalized_quantity=approved.normalized_quantity,
                normalized_price=approved.normalized_price,
                normalized_notional=approved.normalized_notional,
                checks=checks,
                approved_intent=approved,
                rejected_intent=None,
            )

            if self.audit_storage is not None:
                self.audit_storage.record_decision(decision, intent)

            return decision

        except Exception as exc:
            logger.error("Exceção não tratada no LiveSafetyGate (Fail-Closed): %s", exc.__class__.__name__)
            return self._reject(
                intent,
                "SAFETY_GATE_EXCEPTION",
                f"Falha de integridade interna no LiveSafetyGate: {exc.__class__.__name__}.",
                checks,
                now_iso,
            )

    def _reject(
        self,
        intent: OrderIntent,
        reason_code: str,
        reason: str,
        checks: dict[str, Any],
        rejected_at: str,
    ) -> SafetyDecision:
        """Cria e registra uma rejeição fail-closed."""
        checks["failed_check"] = reason_code
        rejected = RejectedOrderIntent(
            intent=intent,
            reason_code=reason_code,
            reason=reason,
            checks=checks,
            rejected_at=rejected_at,
        )
        decision = SafetyDecision(
            allowed=False,
            reason_code=reason_code,
            reason=reason,
            normalized_quantity=None,
            normalized_price=None,
            normalized_notional=None,
            checks=checks,
            approved_intent=None,
            rejected_intent=rejected,
        )

        if self.audit_storage is not None:
            try:
                self.audit_storage.record_decision(decision, intent)
            except Exception as e:
                logger.error("Falha ao registrar auditoria de rejeição: %s", e.__class__.__name__)

        return decision


# =============================================================================
# AUDITORIA LOCAL EM SQLITE
# =============================================================================

class LiveSafetyAuditStorage:
    """Armazenamento local em SQLite para auditoria de decisões do Live Safety Gate."""

    def __init__(self, db_path: str | Path = "data/finbot_paper.sqlite3", timeout: float = 30.0) -> None:
        self.db_path = Path(db_path) if isinstance(db_path, str) and db_path != ":memory:" else db_path
        self.timeout = timeout
        self._memory_conn: sqlite3.Connection | None = None
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        if self.db_path == ":memory:":
            if self._memory_conn is None:
                self._memory_conn = sqlite3.connect(":memory:")
                self._memory_conn.row_factory = sqlite3.Row
            return self._memory_conn

        assert isinstance(self.db_path, Path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=self.timeout)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        """Cria a tabela live_safety_decisions de forma idempotente."""
        with self._transaction() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS live_safety_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    correlation_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    requested_notional TEXT NOT NULL,
                    normalized_notional TEXT,
                    allowed INTEGER NOT NULL,
                    reason_code TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    checks_json TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_live_safety_correlation
                ON live_safety_decisions(correlation_id)
                """
            )

    @contextmanager
    def _transaction(self) -> Generator[sqlite3.Connection, None, None]:
        conn = self.get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            if self.db_path != ":memory:":
                conn.close()

    def record_decision(self, decision: SafetyDecision, intent: OrderIntent) -> int:
        """Registra uma decisão na auditoria local. NUNCA contém credenciais ou chaves."""
        with self._transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO live_safety_decisions (
                    correlation_id, timestamp, symbol, side,
                    requested_notional, normalized_notional,
                    allowed, reason_code, reason, checks_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    intent.correlation_id,
                    datetime.now(timezone.utc).isoformat(),
                    intent.symbol,
                    intent.side,
                    str(intent.requested_notional),
                    str(decision.normalized_notional) if decision.normalized_notional is not None else None,
                    1 if decision.allowed else 0,
                    decision.reason_code,
                    decision.reason,
                    json.dumps(decision.checks),
                ),
            )
            return cursor.lastrowid or 0

    def get_recent_decisions(self, limit: int = 50) -> list[dict[str, Any]]:
        """Recupera as decisões mais recentes para auditoria."""
        with self._transaction() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM live_safety_decisions
                ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]
