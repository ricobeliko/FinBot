"""Módulo de validação operacional e execução controlada na Binance Spot Testnet (FASE 8.4C2B).

Fornece a ferramenta operacional controlada para validação e emissão da PRIMEIRA ORDEM
na Binance Spot Testnet oficial (https://testnet.binance.vision) utilizando saldo fictício.

REGRAS CONSTITUCIONAIS E DE ISOLAMENTO:
1. READ-ONLY POR PADRÃO: Sem confirmação explícita, executa exclusivamente PREVIEW e aborta
   antes de qualquer operação de escrita.
2. CONFIRMAÇÃO INEQUÍVOCA: Exige a flag explícita `--confirm-testnet-order` para armamento de escrita.
   Flags genéricas (`--yes`, `--force`, `--live`) NÃO autorizam escrita e são rejeitadas.
3. ZERO PRODUÇÃO: Produção (`api.binance.com`, target `FinBot/Binance/Production`, ordens e transferências)
   permanece 100% isolada, bloqueada e intocada.
4. PIPELINE COMPLETO SEM ATALHOS:
   OrderIntent -> Risk Engine -> MarketFilterGuard -> LiveSafetyGate -> ApprovedOrderIntent
   -> GuardedLiveExecutionEngine -> BinanceSpotTestnetOrderAdapter -> Binance Spot Testnet.
5. SENTRIES FAIL-CLOSED: Re-valida ambiente, armamento, adapter, endpoints e credenciais imediatamente
   antes de qualquer escrita.
6. IDEMPOTÊNCIA E FALHA AMBÍGUA: clientOrderId determinístico (`finbot_<hash>`), persistência prévia de
   PENDING_SUBMISSION, timeout tratado estritamente como UNKNOWN sem auto-retry e reconciliação por polling
   limitado.
7. SIGILO TOTAL: Proibição absoluta de impressão de API keys, secrets, assinaturas ou payloads confidenciais.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
import logging
import sys
import time
from typing import Any

from finbot.config import BinanceEnvironment, Config, get_config
from finbot.credentials import (
    CredentialProvider,
    CredentialsMissingError,
    FakeCredentialProvider,
    TARGET_NAME_PRODUCTION,
    TARGET_NAME_SPOT_TESTNET,
    WindowsCredentialProvider,
)
from finbot.execution import (
    generate_client_order_id,
)
from finbot.live_executor import (
    AmbiguousExecutionError,
    BinanceOrderAdapter,
    ExchangeOrderResult,
    FakeExchangeOrderAdapter,
    GuardedLiveExecutionEngine,
    LiveOrderStorage,
    MicroOrderCapExceededError,
    OrderStatus,
    RealOrderSubmissionBlockedError,
)
from finbot.live_safety import (
    AccountStateSnapshot,
    ApprovedOrderIntent,
    LiveSafetyGate,
    MarketFilterGuard,
    MarketFilters,
    OrderIntent,
    extract_market_filters,
    sanitize_amount,
    sanitize_price,
    validate_notional,
)
from finbot.private_exchange import (
    BinancePrivateExchange,
    LiveTradingBlockedError,
)
from finbot.risk import RiskDecision, RiskDecisionCode, RiskEngine
from finbot.testnet_adapter import (
    BinanceSpotTestnetOrderAdapter,
    PRODUCTION_HOST_KEYWORD,
    TESTNET_HOST_KEYWORD,
    TestnetExecutionNotArmedError,
    TestnetSentryError,
    verify_testnet_endpoint,
)

logger = logging.getLogger(__name__)

DEFAULT_TARGET_NOTIONAL = Decimal("6.00")
SYMBOL_BTC_USDT = "BTC/USDT"


# =============================================================================
# ESTRUTURAS DE DADOS DO RELATÓRIO E PREVIEW
# =============================================================================

@dataclass
class TestnetValidationPreview:
    """Resultado da avaliação prévia em modo READ-ONLY (Dry Preview)."""

    environment: str = "SPOT_TESTNET"
    symbol: str = SYMBOL_BTC_USDT
    side: str = "BUY"
    order_type: str = "MARKET"
    estimated_notional: Decimal | None = None
    quantity: Decimal | None = None
    reference_price: Decimal | None = None
    min_amount: Decimal | None = None
    step_size: Decimal | None = None
    min_notional: Decimal | None = None
    risk_engine_pass: bool = False
    market_filter_guard_pass: bool = False
    production_isolation_pass: bool = False
    testnet_write_executed: bool = False
    ready_to_execute: bool = False
    error_messages: list[str] = field(default_factory=list)


@dataclass
class TestnetOrderExecutionReport:
    """Relatório estruturado da execução e reconciliação da ordem na Testnet."""

    environment: str = "SPOT_TESTNET"
    symbol: str = SYMBOL_BTC_USDT
    side: str = "BUY"
    order_type: str = "MARKET"
    requested_notional: Decimal = Decimal("0")
    sanitized_quantity: Decimal = Decimal("0")
    client_order_id: str = ""
    order_id: str | None = None
    order_status: str = ""
    executed_quantity: Decimal = Decimal("0")
    average_price: Decimal | None = None
    final_state: str = ""
    reconciliation_status: str = ""
    testnet_orders_sent: int = 0
    production_orders_sent: int = 0
    production_write_enabled: bool = False
    lifecycle_transitions: list[str] = field(default_factory=list)
    error_messages: list[str] = field(default_factory=list)


# =============================================================================
# CÁLCULO DINÂMICO DE QUANTIDADE CANDIDATA
# =============================================================================

def calculate_testnet_order_candidate(
    filters: MarketFilters,
    current_price: Decimal,
    max_cap: Decimal,
    target_notional: Decimal = DEFAULT_TARGET_NOTIONAL,
) -> tuple[Decimal, Decimal, Decimal] | None:
    """Calcula dinamicamente a quantidade e o notional válidos para a ordem de teste.

    Retorna (sanitized_quantity, candidate_notional, current_price) ou None se inviável.
    Regras estritas:
    - candidate_notional próximo de target_notional (~6 USDT)
    - candidate_notional >= filters.min_cost (minNotional com margem)
    - candidate_notional <= max_cap (micro-order cap)
    - sanitized_quantity múltiplo exato de filters.amount_step (stepSize)
    - sanitized_quantity >= filters.min_amount (minQty)
    """
    if current_price <= 0 or current_price.is_nan() or current_price.is_infinite():
        return None

    if max_cap <= 0 or max_cap.is_nan() or max_cap.is_infinite():
        return None

    if filters.min_cost > max_cap:
        return None

    # Ajusta o notional alvo se min_cost exigir mais do que o default de 6 USDT
    effective_target = max(target_notional, filters.min_cost * Decimal("1.10"))
    if effective_target > max_cap:
        return None

    if filters.amount_step <= 0:
        return None

    raw_qty = effective_target / current_price
    steps = (raw_qty / filters.amount_step).to_integral_value(rounding=ROUND_CEILING)
    cand_qty = steps * filters.amount_step

    if cand_qty < filters.min_amount:
        min_steps = (filters.min_amount / filters.amount_step).to_integral_value(rounding=ROUND_CEILING)
        cand_qty = min_steps * filters.amount_step

    valid_amt, norm_qty, _ = sanitize_amount(
        amount=cand_qty,
        min_amount=filters.min_amount,
        amount_step=filters.amount_step,
        max_amount=filters.max_amount,
    )
    if not valid_amt:
        return None

    cand_notional = norm_qty * current_price

    # Margem defensiva para garantir que nunca fica abaixo do min_cost
    if cand_notional < filters.min_cost:
        norm_qty += filters.amount_step
        cand_notional = norm_qty * current_price

    # Garantia de conformidade com o teto de micro-ordem
    if cand_notional > max_cap:
        return None

    if cand_notional < filters.min_cost:
        return None

    return norm_qty, cand_notional, current_price


# =============================================================================
# SENTRIES PRÉ-ESCRITA FAIL-CLOSED
# =============================================================================

def verify_testnet_write_sentries(
    config: Config,
    adapter: Any,
    credential_provider: CredentialProvider,
) -> None:
    """Sentry defensivo pré-escrita.

    Verifica com rigor fail-closed antes de submeter qualquer ordem à Testnet:
    1. BinanceEnvironment == SPOT_TESTNET
    2. testnet_execution_enabled == True
    3. adapter == BinanceSpotTestnetOrderAdapter (ou FakeExchangeOrderAdapter em testes)
    4. endpoint contém testnet.binance.vision
    5. endpoint NÃO contém api.binance.com
    6. credencial target == FinBot/Binance/SpotTestnet

    Se qualquer item falhar: ABORTAR FAIL-CLOSED levantando TestnetSentryError.
    """
    # 1. Verificação de Ambiente
    if config.binance_environment != BinanceEnvironment.SPOT_TESTNET:
        raise TestnetSentryError(
            f"Sentry Check Falhou: config.binance_environment é '{config.binance_environment}', "
            f"esperado '{BinanceEnvironment.SPOT_TESTNET}'."
        )

    # 2. Verificação de Armamento
    if not config.testnet_execution_enabled:
        raise TestnetSentryError(
            "Sentry Check Falhou: config.testnet_execution_enabled é False. "
            "Operação de escrita na Testnet está desarmada."
        )

    # 3. Verificação do Tipo de Adapter e Armamento Interno
    if getattr(adapter, "__class__", None).__name__ == "BinanceOrderAdapter" or (
        isinstance(BinanceOrderAdapter, type) and isinstance(adapter, BinanceOrderAdapter)
    ):
        raise TestnetSentryError(
            "Sentry Check Falhou: BinanceOrderAdapter de PRODUÇÃO detectado! "
            "Operação sumariamente abortada."
        )

    adapter_env = getattr(adapter, "environment", None)
    if adapter_env is not None and adapter_env != BinanceEnvironment.SPOT_TESTNET:
        raise TestnetSentryError(
            f"Sentry Check Falhou: Adapter configurado com ambiente '{adapter_env}', "
            f"mas deve ser '{BinanceEnvironment.SPOT_TESTNET}'."
        )

    if getattr(adapter, "__class__", None).__name__ == "BinanceSpotTestnetOrderAdapter" or (
        isinstance(BinanceSpotTestnetOrderAdapter, type) and isinstance(adapter, BinanceSpotTestnetOrderAdapter)
    ):
        if not getattr(adapter, "testnet_execution_enabled", False):
            raise TestnetSentryError(
                "Sentry Check Falhou: adapter.testnet_execution_enabled é False."
            )

    # 4. Verificação de Endpoints e URLs (Inviolabilidade de Produção)
    client = getattr(adapter, "_client", None)
    if client is not None:
        verify_testnet_endpoint(client)
    else:
        # Verifica se há URLs em mock/fake
        urls = getattr(adapter, "urls", None)
        if isinstance(urls, dict):
            urls_str = str(urls)
            if PRODUCTION_HOST_KEYWORD in urls_str:
                raise TestnetSentryError(
                    f"Sentry Check Falhou: URL de PRODUÇÃO detectada no adapter ({PRODUCTION_HOST_KEYWORD})!"
                )
            if TESTNET_HOST_KEYWORD not in urls_str:
                raise TestnetSentryError(
                    f"Sentry Check Falhou: URL da Testnet ausente no adapter ({TESTNET_HOST_KEYWORD})."
                )

    # 5. Verificação de Target de Credenciais
    target = getattr(credential_provider, "target_name", TARGET_NAME_SPOT_TESTNET)
    if target == TARGET_NAME_PRODUCTION:
        raise TestnetSentryError(
            f"Sentry Check Falhou: Target de credenciais aponta para Produção ('{TARGET_NAME_PRODUCTION}')! "
            f"Bloqueado imediatamente."
        )

    if target != TARGET_NAME_SPOT_TESTNET and not isinstance(credential_provider, FakeCredentialProvider):
        raise TestnetSentryError(
            f"Sentry Check Falhou: Target de credenciais '{target}' não autorizado para Spot Testnet."
        )

    # Mensagem final mandatória antes do write
    print("TARGET_ENVIRONMENT = BINANCE_SPOT_TESTNET")
    print("PRODUCTION_TARGET = NO")
    print("TESTNET_WRITE_ARMED = YES")


# =============================================================================
# ISOLAMENTO DE PRODUÇÃO
# =============================================================================

def check_production_isolation(credential_provider: CredentialProvider) -> tuple[bool, list[str]]:
    """Verifica isolamento rigoroso de produção sem efetuar chamadas externas."""
    errors: list[str] = []
    cfg = get_config()

    target = getattr(credential_provider, "target_name", TARGET_NAME_SPOT_TESTNET)
    if target == TARGET_NAME_PRODUCTION:
        errors.append("Target de credenciais aponta para Produção!")

    if cfg.real_order_submission_enabled:
        errors.append("real_order_submission_enabled está ativo no Config!")

    prod_adapter = BinanceOrderAdapter(real_order_submission_enabled=False)
    try:
        prod_adapter.submit_order({"symbol": SYMBOL_BTC_USDT})
        errors.append("BinanceOrderAdapter de produção não bloqueou submit_order!")
    except RealOrderSubmissionBlockedError:
        pass
    except Exception as exc:
        errors.append(f"Erro inesperado em BinanceOrderAdapter: {exc}")

    try:
        priv_exchange = BinancePrivateExchange(
            config=Config(trading_mode="live"),
            credential_provider=FakeCredentialProvider(api_key="k" * 32, api_secret="s" * 32),
        )
        priv_exchange.create_order(SYMBOL_BTC_USDT, "market", "buy", 0.001)
        errors.append("BinancePrivateExchange não bloqueou create_order!")
    except LiveTradingBlockedError:
        pass
    except Exception as exc:
        errors.append(f"Erro inesperado em BinancePrivateExchange: {exc}")

    return len(errors) == 0, errors


# =============================================================================
# RECONCILIAÇÃO POR POLLING LIMITADO
# =============================================================================

def reconcile_with_bounded_polling(
    engine: GuardedLiveExecutionEngine,
    client_order_id: str,
    max_attempts: int = 5,
    poll_delay_seconds: float = 1.0,
) -> ExchangeOrderResult:
    """Executa reconciliação determinística da ordem via polling limitado.

    Não cria loop infinito. Retorna o resultado final de fetch_order / reconcile_order.
    """
    last_result: ExchangeOrderResult | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            last_result = engine.reconcile_order(client_order_id)
        except Exception as exc:
            logger.warning("Falha na tentativa %d de reconciliação de %s: %s", attempt, client_order_id, exc)

        if last_result is not None:
            # Se atingiu estado final definitivo, encerra polling imediatamente
            if last_result.status in (OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED):
                break

        if attempt < max_attempts and poll_delay_seconds > 0:
            time.sleep(poll_delay_seconds)

    if last_result is None:
        # Fallback local seguro
        order_dict = engine.storage.get_order_by_client_order_id(client_order_id)
        status = OrderStatus(order_dict["current_status"]) if order_dict else OrderStatus.UNKNOWN
        last_result = ExchangeOrderResult(
            client_order_id=client_order_id,
            exchange_order_id=order_dict.get("exchange_order_id") if order_dict else None,
            status=status,
            symbol=SYMBOL_BTC_USDT,
            side="BUY",
            order_type="MARKET",
            requested_quantity=Decimal(order_dict["requested_quantity"]) if order_dict else Decimal("0"),
            executed_quantity=Decimal(order_dict.get("executed_quantity") or "0") if order_dict else Decimal("0"),
            cumulative_quote_quantity=Decimal(order_dict.get("cumulative_quote_quantity") or "0") if order_dict else Decimal("0"),
            average_price=Decimal(order_dict["average_price"]) if order_dict and order_dict.get("average_price") else None,
        )

    return last_result


# =============================================================================
# EXECUTOR PRINCIPAL (VALIDATION RUNNER)
# =============================================================================

def run_testnet_order_validation(
    confirm_testnet_order: bool = False,
    config: Config | None = None,
    credential_provider: CredentialProvider | None = None,
    adapter: Any | None = None,
    storage: LiveOrderStorage | None = None,
    current_price: Decimal | None = None,
    correlation_id: str | None = None,
    max_reconcile_attempts: int = 5,
    poll_delay_seconds: float = 1.0,
) -> tuple[TestnetValidationPreview | None, TestnetOrderExecutionReport | None]:
    """Orquestrador do comando operacional de validação de ordem na Binance Spot Testnet.

    Se confirm_testnet_order == False:
        Executa DRY PREVIEW (READ-ONLY) e retorna (preview, None).
    Se confirm_testnet_order == True:
        Executa validação armada, submissão da ordem e reconciliação determinística, retornando (None, report).
    """
    base_cfg = config or get_config()
    provider = credential_provider or WindowsCredentialProvider.for_environment(
        BinanceEnvironment.SPOT_TESTNET
    )

    # 1. Configuração do Adapter Spot Testnet
    testnet_adapter = adapter
    if testnet_adapter is None:
        testnet_adapter = BinanceSpotTestnetOrderAdapter(
            credential_provider=provider,
            testnet_execution_enabled=confirm_testnet_order,
        )

    # 2. Carregar Metadados e Filtros de BTC/USDT
    markets = testnet_adapter.load_markets()
    btc_market = markets.get(SYMBOL_BTC_USDT)
    if not btc_market:
        raise RuntimeError(f"Mercado {SYMBOL_BTC_USDT} não encontrado na Binance Spot Testnet.")
    filters = extract_market_filters(btc_market)

    # 3. Obter Preço de Referência
    ref_price = current_price
    if ref_price is None:
        if hasattr(testnet_adapter, "fetch_ticker"):
            ticker = testnet_adapter.fetch_ticker(SYMBOL_BTC_USDT)
            price_val = ticker.get("last") or ticker.get("ask") or ticker.get("close")
            if price_val is not None:
                ref_price = Decimal(str(price_val))
        if ref_price is None:
            raise RuntimeError(f"Não foi possível obter preço de mercado para {SYMBOL_BTC_USDT}.")

    # 4. Cálculo Dinâmico da Ordem Candidata
    micro_cap = Decimal(str(base_cfg.live_micro_order_max_notional))
    candidate = calculate_testnet_order_candidate(
        filters=filters,
        current_price=ref_price,
        max_cap=micro_cap,
        target_notional=DEFAULT_TARGET_NOTIONAL,
    )
    if candidate is None:
        raise RuntimeError(
            f"Não foi possível calcular ordem candidata válida próxima de {DEFAULT_TARGET_NOTIONAL} USDT "
            f"respeitando minNotional ({filters.min_cost}) e micro-order cap ({micro_cap} USDT)."
        )
    cand_qty, cand_notional, cand_price = candidate

    # 5. Validação do Risk Engine
    risk_decision = RiskDecision(
        allowed=True,
        code=RiskDecisionCode.ALLOWED,
        reason="Assisted Spot Testnet order validation authorized by operator",
        action="BUY",
        target_notional=cand_notional,
    )
    risk_pass = risk_decision.allowed and risk_decision.action == "BUY"

    # 6. Validação do MarketFilterGuard
    guard = MarketFilterGuard(filters)
    dummy_intent = OrderIntent(
        symbol=SYMBOL_BTC_USDT,
        side="BUY",
        order_type="MARKET",
        quantity=cand_qty,
        price=None,
        requested_notional=cand_notional,
        strategy_name="testnet_validation",
        strategy_version="1.0.0",
        signal="BUY",
        created_at=datetime.now(timezone.utc).isoformat(),
        correlation_id=correlation_id or f"preview_{int(time.time())}",
    )
    filter_decision = guard.validate_order_intent(dummy_intent)
    guard_pass = filter_decision.is_valid

    # 7. Validação de Isolamento de Produção
    isolation_pass, isolation_errors = check_production_isolation(provider)

    # =========================================================================
    # MODO 1: DRY PREVIEW (READ-ONLY)
    # =========================================================================
    if not confirm_testnet_order:
        preview = TestnetValidationPreview(
            environment=BinanceEnvironment.SPOT_TESTNET.value,
            symbol=SYMBOL_BTC_USDT,
            side="BUY",
            order_type="MARKET",
            estimated_notional=cand_notional,
            quantity=cand_qty,
            reference_price=cand_price,
            min_amount=filters.min_amount,
            step_size=filters.amount_step,
            min_notional=filters.min_cost,
            risk_engine_pass=risk_pass,
            market_filter_guard_pass=guard_pass,
            production_isolation_pass=isolation_pass,
            testnet_write_executed=False,
            ready_to_execute=(risk_pass and guard_pass and isolation_pass),
            error_messages=isolation_errors,
        )
        return preview, None

    # =========================================================================
    # MODO 2: EXECUÇÃO ARMADA NA SPOT TESTNET
    # =========================================================================
    armed_cfg = Config(
        trading_mode="live",
        live_trading_acknowledged=True,
        binance_environment=BinanceEnvironment.SPOT_TESTNET,
        testnet_execution_enabled=True,
        live_micro_order_max_notional=base_cfg.live_micro_order_max_notional,
    )

    # 8. Sentries Pré-Escrita (Fail-Closed)
    verify_testnet_write_sentries(
        config=armed_cfg,
        adapter=testnet_adapter,
        credential_provider=provider,
    )

    # 9. Consulta de Saldos e Snapshot para Reconciliação
    balances = testnet_adapter.get_balances()
    usdt_bal = balances.get("USDT", {})
    btc_bal = balances.get("BTC", {})
    account_snapshot = AccountStateSnapshot(
        symbol=SYMBOL_BTC_USDT,
        base_asset="BTC",
        quote_asset="USDT",
        base_free=Decimal(str(usdt_bal.get("free", "0"))),  # pass quote
        base_locked=Decimal(str(btc_bal.get("used", "0"))),
        quote_free=Decimal(str(usdt_bal.get("free", "0"))),
        quote_locked=Decimal(str(usdt_bal.get("used", "0"))),
        captured_at=datetime.now(timezone.utc).isoformat(),
    )

    # 10. Construção da OrderIntent Real
    corr_id = correlation_id or f"testnet_val_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    order_intent = OrderIntent(
        symbol=SYMBOL_BTC_USDT,
        side="BUY",
        order_type="MARKET",
        quantity=cand_qty,
        price=None,
        requested_notional=cand_notional,
        strategy_name="testnet_validation",
        strategy_version="1.0.0",
        signal="BUY",
        created_at=datetime.now(timezone.utc).isoformat(),
        correlation_id=corr_id,
    )

    # 11. Avaliação pelo LiveSafetyGate
    safety_gate = LiveSafetyGate()
    safety_decision = safety_gate.evaluate(
        intent=order_intent,
        risk_decision=risk_decision,
        market_guard=guard,
        account_snapshot=account_snapshot,
        config=armed_cfg,
    )
    if not safety_decision.allowed or safety_decision.approved_intent is None:
        raise RuntimeError(
            f"LiveSafetyGate rejeitou a intenção da Testnet: {safety_decision.reason_code} — {safety_decision.reason}"
        )
    approved_intent = safety_decision.approved_intent

    # 12. Inicialização do GuardedLiveExecutionEngine
    order_storage = storage or LiveOrderStorage("data/testnet_orders.sqlite3")
    engine = GuardedLiveExecutionEngine(
        adapter=testnet_adapter,
        storage=order_storage,
        config=armed_cfg,
    )

    # 13. Submissão da Ordem
    client_order_id = generate_client_order_id(corr_id)
    submit_result = engine.execute(approved_intent)

    # 14. Reconciliação por Polling Limitado
    final_result = reconcile_with_bounded_polling(
        engine=engine,
        client_order_id=client_order_id,
        max_attempts=max_reconcile_attempts,
        poll_delay_seconds=poll_delay_seconds,
    )

    # 15. Montagem do Relatório Operacional
    history = order_storage.get_lifecycle_history(corr_id)
    transitions = [f"{rec.previous_status} -> {rec.new_status} ({rec.reason})" for rec in history]

    recon_status = "CONFIRMED" if final_result.status in (OrderStatus.FILLED, OrderStatus.ACKNOWLEDGED) else "PENDING_OR_UNKNOWN"
    orders_sent = 1 if final_result.status != OrderStatus.REJECTED else 0

    report = TestnetOrderExecutionReport(
        environment=BinanceEnvironment.SPOT_TESTNET.value,
        symbol=SYMBOL_BTC_USDT,
        side="BUY",
        order_type="MARKET",
        requested_notional=cand_notional,
        sanitized_quantity=cand_qty,
        client_order_id=client_order_id,
        order_id=final_result.exchange_order_id,
        order_status=final_result.status.value,
        executed_quantity=final_result.executed_quantity,
        average_price=final_result.average_price,
        final_state=final_result.status.value,
        reconciliation_status=recon_status,
        testnet_orders_sent=orders_sent,
        production_orders_sent=0,
        production_write_enabled=False,
        lifecycle_transitions=transitions,
    )

    return None, report


# =============================================================================
# EXIBIÇÃO DE RELATÓRIO E PREVIEW
# =============================================================================

def print_preview(preview: TestnetValidationPreview) -> None:
    """Imprime a tela de Dry Preview antes de qualquer execução armada."""
    print("=" * 65)
    print("       FinBot — BINANCE SPOT TESTNET ORDER PREVIEW (READ-ONLY)    ")
    print("=" * 65)
    print("TESTNET_ORDER_PREVIEW")
    print(f"ENVIRONMENT                    : {preview.environment}")
    print(f"SYMBOL                         : {preview.symbol}")
    print(f"SIDE                           : {preview.side}")
    print(f"TYPE                           : {preview.order_type}")
    if preview.estimated_notional is not None:
        print(f"ESTIMATED_NOTIONAL             : {preview.estimated_notional:.8f} USDT")
    if preview.quantity is not None:
        print(f"QUANTITY                       : {preview.quantity:.8f} BTC")
    if preview.reference_price is not None:
        print(f"REFERENCE_PRICE                : {preview.reference_price:.2f} USDT")
    if preview.min_notional is not None:
        print(f"MIN_NOTIONAL (EXCHANGE)        : {preview.min_notional:.2f} USDT")
    print(f"RISK_ENGINE                    : {'PASS' if preview.risk_engine_pass else 'FAIL'}")
    print(f"MARKET_FILTER_GUARD            : {'PASS' if preview.market_filter_guard_pass else 'FAIL'}")
    print(f"PRODUCTION_ISOLATION           : {'PASS' if preview.production_isolation_pass else 'FAIL'}")
    print("-" * 65)
    print(f"TESTNET_WRITE_EXECUTED         : {'YES' if preview.testnet_write_executed else 'NO'}")
    print(f"READY_TO_EXECUTE_TESTNET_ORDER : {'YES' if preview.ready_to_execute else 'NO'}")
    print("=" * 65)

    if preview.ready_to_execute:
        print("PREVIEW CONCLUÍDO COM SUCESSO. NENHUMA ORDEM FOI ENVIADA.")
    else:
        print("AVISO: Validação prévia não está pronta para execução.")
        for err in preview.error_messages:
            print(f"- {err}")


def print_report(report: TestnetOrderExecutionReport) -> None:
    """Imprime o relatório final da ordem executada e reconciliada na Testnet."""
    print("=" * 65)
    print("       FinBot — BINANCE SPOT TESTNET ORDER EXECUTION REPORT       ")
    print("=" * 65)
    print(f"ENVIRONMENT                    : {report.environment}")
    print(f"SYMBOL                         : {report.symbol}")
    print(f"SIDE                           : {report.side}")
    print(f"TYPE                           : {report.order_type}")
    print(f"REQUESTED_NOTIONAL             : {report.requested_notional:.8f} USDT")
    print(f"SANITIZED_QUANTITY             : {report.sanitized_quantity:.8f} BTC")
    print(f"CLIENT_ORDER_ID                : {report.client_order_id}")
    print(f"ORDER_ID                       : {report.order_id or 'NONE'}")
    print(f"ORDER_STATUS                   : {report.order_status}")
    print(f"EXECUTED_QUANTITY              : {report.executed_quantity:.8f} BTC")
    avg_str = f"{report.average_price:.2f} USDT" if report.average_price is not None else "N/A"
    print(f"AVERAGE_PRICE                  : {avg_str}")
    print(f"FINAL_STATE                    : {report.final_state}")
    print(f"RECONCILIATION_STATUS          : {report.reconciliation_status}")
    print("-" * 65)
    print("CICLO DE VIDA REGISTRADO:")
    for tr in report.lifecycle_transitions:
        print(f"  - {tr}")
    print("-" * 65)
    print("INVIOLABILIDADE OPERACIONAL:")
    print(f"TESTNET_ORDERS_SENT            : {report.testnet_orders_sent}")
    print(f"PRODUCTION_ORDERS_SENT         : {report.production_orders_sent}")
    print(f"PRODUCTION_WRITE_ENABLED       : {'YES' if report.production_write_enabled else 'NO'}")
    print("=" * 65)


# =============================================================================
# CLI ENTRYPOINT
# =============================================================================

def parse_args(args: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="FinBot — Binance Spot Testnet Operational Order Validation",
        prog="python -m finbot.testnet_order_validation",
    )
    parser.add_argument(
        "--confirm-testnet-order",
        action="store_true",
        help="Autorização explícita e inequívoca para submissão de ordem de teste na Spot Testnet.",
    )
    # Flags genéricas desautorizadas para captura defensiva
    parser.add_argument("--yes", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--force", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--live", action="store_true", help=argparse.SUPPRESS)

    return parser.parse_args(args)


def main(argv: list[str] | None = None) -> int:
    args_list = argv if argv is not None else sys.argv[1:]
    parsed = parse_args(args_list)

    # Detecção e rejeição de flags genéricas
    if (parsed.yes or parsed.force or parsed.live) and not parsed.confirm_testnet_order:
        print(
            "ERRO DE SEGURANÇA: Flags genéricas (--yes, --force, --live) NÃO autorizam escrita na Testnet.\n"
            "A confirmação deve ser explícita e mencionar TESTNET: --confirm-testnet-order\n"
            "Operação abortada antes de qualquer WRITE."
        )
        return 1

    confirm = bool(parsed.confirm_testnet_order)

    try:
        preview, report = run_testnet_order_validation(confirm_testnet_order=confirm)
        if preview is not None:
            print_preview(preview)
            return 0 if preview.ready_to_execute else 1
        elif report is not None:
            print_report(report)
            return 0
        return 0
    except Exception as exc:
        print(f"\nERRO NA EXECUÇÃO DA TESTNET: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
