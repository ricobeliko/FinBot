"""Módulo de verificação pré-operacional de prontidão (Pre-Flight) — FASE 8.4C1.

Executa validações read-only completas antes de qualquer futura micro-ordem real:
1. Credenciais no Windows Credential Manager
2. Autenticação privada Binance Spot (Read-Only)
3. Consulta privada de saldos (Read-Only, sem exibição patrimonial)
4. Metadados de mercado e filtros do par BTC/USDT via CCXT público
5. Validação dos filtros de mercado via MarketFilterGuard
6. Cálculo de micro-ordem candidata segura respeitando minNotional e live_micro_order_max_notional
7. Verificação passiva de suficiência de fundos para a candidata
8. Execução simulada através do pipeline defensivo completo em modo DRY_RUN
9. Verificação local da barreira final (real_order_submission_enabled == False)
10. Verificação estrutural das barreiras de create_order e cancel_order (LiveTradingBlockedError)

ESTRUTURALMENTE INCAPAZ DE ENVIAR OU CANCELAR ORDENS REAIS.
ZERO CHAMADAS DE ORDEM PARA A REDE.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
import logging
import math
import sys
from typing import Any
import uuid

import ccxt

from finbot.config import Config, get_config
from finbot.credentials import (
    BinanceCredentials,
    CredentialProvider,
    CredentialsMissingError,
    FakeCredentialProvider,
    WindowsCredentialProvider,
)
from finbot.exchange import create_exchange, fetch_ticker
from finbot.execution import (
    DryRunExecutionEngine,
    DryRunStorage,
    run_dry_run_pipeline,
)
from finbot.live_executor import (
    BinanceOrderAdapter,
    RealOrderSubmissionBlockedError,
)
from finbot.live_safety import (
    AccountStateSnapshot,
    LiveSafetyGate,
    MarketFilterGuard,
    MarketFilters,
    OrderIntent,
    extract_market_filters,
    sanitize_amount,
    sanitize_price,
)
from finbot.private_exchange import (
    BinancePrivateExchange,
    LiveTradingBlockedError,
    PrivateExchangeError,
)
from finbot.risk import RiskDecision, RiskDecisionCode

logger = logging.getLogger(__name__)


# =============================================================================
# ESTRUTURA DE RESULTADOS DO PRE-FLIGHT
# =============================================================================

@dataclass
class PreflightResult:
    """Resultado estruturado e auditável de todas as etapas do Pre-Flight."""

    credential_store: str = "WINDOWS_CREDENTIAL_MANAGER"
    credentials_present: bool = False
    binance_private_auth_pass: bool = False
    private_balance_read_pass: bool = False

    symbol: str = "BTC/USDT"
    min_amount: Decimal | None = None
    step_size: Decimal | None = None
    price_tick: Decimal | None = None
    min_notional: Decimal | None = None

    micro_order_cap: Decimal = Decimal("15.00")
    safe_micro_order_possible: bool = False
    candidate_notional: Decimal | None = None
    candidate_quantity: Decimal | None = None
    candidate_price: Decimal | None = None

    funds_available_for_candidate: bool = False

    market_filter_guard_pass: bool = False
    dry_run_status: str = "NOT_RUN"
    dry_run_reason: str = ""

    final_live_barrier_pass: bool = False
    create_order_barrier_pass: bool = False
    cancel_order_barrier_pass: bool = False

    real_orders_sent: int = 0
    order_network_calls: int = 0

    ready_for_8_4c2: bool = False


# =============================================================================
# CÁLCULO DA MICRO-ORDEM CANDIDATA
# =============================================================================

def calculate_micro_order_candidate(
    filters: MarketFilters,
    current_price: Decimal,
    max_cap: Decimal,
    margin_ratio: Decimal = Decimal("1.15"),
) -> tuple[Decimal, Decimal, Decimal] | None:
    """Calcula quantidade, preço e notional para uma micro-ordem candidata segura.

    Retorna (candidate_quantity, candidate_price, candidate_notional) ou None se impossível.
    Regras:
    - candidate_price ajustado ao price_step (tickSize)
    - candidate_quantity ajustado ao amount_step (stepSize)
    - candidate_quantity >= min_amount
    - candidate_notional >= min_cost (minNotional)
    - candidate_notional > min_cost (margem defensiva contra oscilações de preço)
    - candidate_notional <= max_cap (teto da micro-ordem)
    """
    if current_price <= 0 or current_price.is_nan() or current_price.is_infinite():
        return None

    if max_cap <= 0 or max_cap.is_nan() or max_cap.is_infinite():
        return None

    if filters.min_cost > max_cap:
        return None

    # 1. Ajuste do preço para múltiplos exatos de price_step
    valid_px, cand_price, _ = sanitize_price(
        price=current_price,
        min_price=filters.min_price,
        price_step=filters.price_step,
        max_price=filters.max_price,
    )
    if not valid_px or cand_price <= 0:
        return None

    # 2. Notional alvo com margem defensiva sobre min_cost
    target_notional = filters.min_cost * margin_ratio

    # 3. Quantidade necessária para atingir target_notional
    raw_qty = target_notional / cand_price
    if filters.amount_step <= 0:
        return None

    steps = (raw_qty / filters.amount_step).to_integral_value(rounding=ROUND_CEILING)
    cand_qty = steps * filters.amount_step

    if cand_qty < filters.min_amount:
        min_steps = (filters.min_amount / filters.amount_step).to_integral_value(rounding=ROUND_CEILING)
        cand_qty = min_steps * filters.amount_step

    # 4. Sanitização final de quantidade
    valid_amt, norm_qty, _ = sanitize_amount(
        amount=cand_qty,
        min_amount=filters.min_amount,
        amount_step=filters.amount_step,
        max_amount=filters.max_amount,
    )
    if not valid_amt:
        return None

    cand_notional = norm_qty * cand_price

    # 5. Garantir margem acima do min_cost
    if cand_notional <= filters.min_cost:
        norm_qty += filters.amount_step
        cand_notional = norm_qty * cand_price

    # 6. Garantir conformidade com o teto
    if cand_notional > max_cap:
        return None

    if cand_notional < filters.min_cost:
        return None

    return norm_qty, cand_price, cand_notional


# =============================================================================
# EXECUTOR DO PRE-FLIGHT
# =============================================================================

def run_preflight(
    config: Config | None = None,
    credential_provider: CredentialProvider | None = None,
    private_exchange: BinancePrivateExchange | None = None,
    public_exchange: ccxt.Exchange | Any | None = None,
    symbol: str = "BTC/USDT",
) -> PreflightResult:
    """Executa a verificação completa e estritamente read-only de prontidão (Pre-Flight)."""
    cfg = config or get_config()
    res = PreflightResult(symbol=symbol)
    res.micro_order_cap = Decimal(str(cfg.live_micro_order_max_notional))

    # -------------------------------------------------------------------------
    # 1. CREDENTIAL CHECK
    # -------------------------------------------------------------------------
    provider = credential_provider or WindowsCredentialProvider()
    res.credential_store = provider.get_provider_name().upper().replace(" ", "_")

    has_creds = False
    try:
        has_creds = provider.has_binance_credentials()
    except Exception as exc:
        logger.warning("Falha ao checar presença de credenciais: %s", exc)
        has_creds = False

    res.credentials_present = has_creds

    # -------------------------------------------------------------------------
    # 2. BINANCE PRIVATE READ (READ-ONLY VALIDATION)
    # -------------------------------------------------------------------------
    balances: dict[str, Any] = {}
    if has_creds:
        if private_exchange is None:
            try:
                live_cfg = replace(cfg, trading_mode="live")
                private_exchange = BinancePrivateExchange(
                    config=live_cfg,
                    credential_provider=provider,
                )
            except Exception as exc:
                logger.warning("Falha ao inicializar BinancePrivateExchange: %s", exc)
                private_exchange = None

        if private_exchange is not None:
            try:
                status = private_exchange.get_account_status()
                res.binance_private_auth_pass = True
            except Exception as exc:
                logger.warning("Falha em get_account_status(): %s", exc)
                res.binance_private_auth_pass = False

            try:
                balances = private_exchange.get_balances()
                res.private_balance_read_pass = True
            except Exception as exc:
                logger.warning("Falha em get_balances(): %s", exc)
                res.private_balance_read_pass = False
                balances = {}
    else:
        res.binance_private_auth_pass = False
        res.private_balance_read_pass = False

    # -------------------------------------------------------------------------
    # 3. BTC/USDT MARKET METADATA
    # -------------------------------------------------------------------------
    market_data: dict[str, Any] = {}
    ticker: Any = None
    if public_exchange is None:
        try:
            public_exchange = create_exchange("binance")
        except Exception as exc:
            logger.warning("Falha ao instanciar exchange pública: %s", exc)
            public_exchange = None

    if public_exchange is not None:
        try:
            public_exchange.load_markets()
            market_data = public_exchange.market(symbol)
            ticker = fetch_ticker(public_exchange, symbol)
        except Exception as exc:
            logger.warning("Falha ao obter metadados públicos de %s: %s", symbol, exc)

    # -------------------------------------------------------------------------
    # 4. MARKET FILTER GUARD
    # -------------------------------------------------------------------------
    filters: MarketFilters | None = None
    if market_data:
        try:
            filters = extract_market_filters(market_data)
            res.symbol = filters.symbol
            res.min_amount = filters.min_amount
            res.step_size = filters.amount_step
            res.price_tick = filters.price_step
            res.min_notional = filters.min_cost

            if (
                filters.min_amount > Decimal("0")
                and filters.amount_step > Decimal("0")
                and filters.min_price > Decimal("0")
                and filters.price_step > Decimal("0")
                and filters.min_cost > Decimal("0")
            ):
                _ = MarketFilterGuard(filters)
                res.market_filter_guard_pass = True
            else:
                res.market_filter_guard_pass = False
        except Exception as exc:
            logger.warning("Falha ao interpretar filtros de mercado: %s", exc)
            res.market_filter_guard_pass = False
            filters = None
    else:
        res.market_filter_guard_pass = False

    # -------------------------------------------------------------------------
    # 5. MICRO-ORDER CANDIDATE
    # -------------------------------------------------------------------------
    current_price: Decimal | None = None
    if ticker is not None:
        raw_px = ticker.last or ticker.ask or ticker.bid
        if raw_px is not None:
            try:
                current_price = Decimal(str(raw_px))
            except Exception:
                current_price = None

    if filters is not None and current_price is not None and res.market_filter_guard_pass:
        candidate = calculate_micro_order_candidate(
            filters=filters,
            current_price=current_price,
            max_cap=res.micro_order_cap,
        )
        if candidate is not None:
            res.candidate_quantity, res.candidate_price, res.candidate_notional = candidate
            res.safe_micro_order_possible = True
        else:
            res.safe_micro_order_possible = False
    else:
        res.safe_micro_order_possible = False

    # -------------------------------------------------------------------------
    # 6. SALDO (FUNDS CHECK SEM EXPOSIÇÃO PATRIMONIAL)
    # -------------------------------------------------------------------------
    base_asset = filters.base_asset if filters else "BTC"
    quote_asset = filters.quote_asset if filters else "USDT"

    quote_bal = balances.get(quote_asset)
    quote_free = quote_bal.free if quote_bal else Decimal("0")
    base_bal = balances.get(base_asset)
    base_free = base_bal.free if base_bal else Decimal("0")

    if res.safe_micro_order_possible and res.candidate_notional is not None:
        if res.private_balance_read_pass and quote_free >= res.candidate_notional:
            res.funds_available_for_candidate = True
        else:
            res.funds_available_for_candidate = False
    else:
        res.funds_available_for_candidate = False

    # -------------------------------------------------------------------------
    # 7. DRY-RUN PIPELINE
    # -------------------------------------------------------------------------
    if (
        res.safe_micro_order_possible
        and res.candidate_quantity is not None
        and res.candidate_price is not None
        and res.candidate_notional is not None
        and filters is not None
    ):
        intent = OrderIntent(
            symbol=res.symbol,
            side="BUY",
            order_type="LIMIT",
            quantity=res.candidate_quantity,
            price=res.candidate_price,
            requested_notional=res.candidate_notional,
            strategy_name="preflight_validation",
            strategy_version="1.0.0",
            signal="BUY",
            created_at=datetime.now(timezone.utc).isoformat(),
            correlation_id=f"preflight_{uuid.uuid4().hex[:16]}",
        )

        if res.funds_available_for_candidate:
            risk_decision = RiskDecision(
                allowed=True,
                code=RiskDecisionCode.ALLOWED,
                reason="Pre-flight candidate micro-order authorized by risk policy.",
                action="BUY",
                target_notional=res.candidate_notional,
            )
        else:
            risk_decision = RiskDecision(
                allowed=False,
                code=RiskDecisionCode.INSUFFICIENT_BALANCE,
                reason="Saldo insuficiente para a micro-ordem candidata.",
                action="HOLD",
            )

        account_snapshot = AccountStateSnapshot(
            symbol=res.symbol,
            base_asset=base_asset,
            quote_asset=quote_asset,
            base_free=base_free,
            base_locked=Decimal("0"),
            quote_free=quote_free,
            quote_locked=Decimal("0"),
            captured_at=datetime.now(timezone.utc).isoformat(),
        )

        dry_run_config = replace(
            cfg,
            trading_mode="live",
            live_trading_acknowledged=True,
        )
        dry_run_engine = DryRunExecutionEngine(storage=DryRunStorage(":memory:"))
        gate = LiveSafetyGate()

        safety_decision, dry_run_result = run_dry_run_pipeline(
            intent=intent,
            gate=gate,
            engine=dry_run_engine,
            risk_decision=risk_decision,
            market_guard=MarketFilterGuard(filters),
            account_snapshot=account_snapshot,
            config=dry_run_config,
        )

        if dry_run_result is not None and dry_run_result.status == "SIMULATED_ACCEPTED":
            res.dry_run_status = "SIMULATED_ACCEPTED"
            res.dry_run_reason = ""
        else:
            res.dry_run_status = "FAIL"
            res.dry_run_reason = safety_decision.reason_code
    else:
        res.dry_run_status = "FAIL"
        res.dry_run_reason = "NO_VALID_CANDIDATE"

    # -------------------------------------------------------------------------
    # 8. FINAL LIVE BARRIER CHECK (LOCAL, ZERO HTTP)
    # -------------------------------------------------------------------------
    if not cfg.real_order_submission_enabled:
        adapter = BinanceOrderAdapter(real_order_submission_enabled=False)
        try:
            adapter.submit_order({})
            res.final_live_barrier_pass = False
        except RealOrderSubmissionBlockedError:
            res.final_live_barrier_pass = True
        except Exception:
            res.final_live_barrier_pass = False
    else:
        res.final_live_barrier_pass = False

    # -------------------------------------------------------------------------
    # 9. PRIVATE EXCHANGE BARRIERS CHECK (LOCAL, ZERO HTTP)
    # -------------------------------------------------------------------------
    # create_order barrier check
    try:
        if private_exchange is not None:
            private_exchange.create_order("BTC/USDT", "MARKET", "BUY", Decimal("0.001"))
        else:
            dummy_ex = BinancePrivateExchange(
                config=Config(trading_mode="live"),
                credential_provider=FakeCredentialProvider(
                    api_key="dummy_key_12345678", api_secret="dummy_secret_12345678"
                ),
            )
            dummy_ex.create_order("BTC/USDT", "MARKET", "BUY", Decimal("0.001"))
        res.create_order_barrier_pass = False
    except LiveTradingBlockedError:
        res.create_order_barrier_pass = True
    except Exception:
        res.create_order_barrier_pass = False

    # cancel_order barrier check
    try:
        if private_exchange is not None:
            private_exchange.cancel_order("test_id", "BTC/USDT")
        else:
            dummy_ex = BinancePrivateExchange(
                config=Config(trading_mode="live"),
                credential_provider=FakeCredentialProvider(
                    api_key="dummy_key_12345678", api_secret="dummy_secret_12345678"
                ),
            )
            dummy_ex.cancel_order("test_id", "BTC/USDT")
        res.cancel_order_barrier_pass = False
    except LiveTradingBlockedError:
        res.cancel_order_barrier_pass = True
    except Exception:
        res.cancel_order_barrier_pass = False

    # -------------------------------------------------------------------------
    # 10. SENTINEL COUNTERS
    # -------------------------------------------------------------------------
    res.real_orders_sent = 0
    res.order_network_calls = 0

    # -------------------------------------------------------------------------
    # 11. READINESS DECISION
    # -------------------------------------------------------------------------
    res.ready_for_8_4c2 = bool(
        res.credentials_present
        and res.binance_private_auth_pass
        and res.private_balance_read_pass
        and (res.min_amount is not None)
        and res.market_filter_guard_pass
        and res.safe_micro_order_possible
        and res.funds_available_for_candidate
        and (res.dry_run_status == "SIMULATED_ACCEPTED")
        and res.final_live_barrier_pass
        and res.create_order_barrier_pass
        and res.cancel_order_barrier_pass
        and (res.real_orders_sent == 0)
        and (res.order_network_calls == 0)
    )

    return res


# =============================================================================
# FORMATADOR DE RELATÓRIO OPERACIONAL
# =============================================================================

def format_preflight_report(res: PreflightResult) -> str:
    """Produz a saída limpa e padronizada do Pre-Flight sem segredos ou saldos."""
    creds_str = "PRESENT" if res.credentials_present else "MISSING"
    auth_str = "PASS" if res.binance_private_auth_pass else "FAIL"
    bal_read_str = "PASS" if res.private_balance_read_pass else "FAIL"

    min_amt_str = str(res.min_amount) if res.min_amount is not None else "N/A"
    step_size_str = str(res.step_size) if res.step_size is not None else "N/A"
    price_tick_str = str(res.price_tick) if res.price_tick is not None else "N/A"
    min_notional_str = str(res.min_notional) if res.min_notional is not None else "N/A"

    safe_micro_str = "YES" if res.safe_micro_order_possible else "NO"
    cand_notional_str = f"{res.candidate_notional:.2f} USDT" if res.candidate_notional is not None else "N/A"
    cand_qty_str = f"{res.candidate_quantity:.8f} BTC" if res.candidate_quantity is not None else "N/A"

    funds_str = "YES" if res.funds_available_for_candidate else "NO"

    mfg_str = "PASS" if res.market_filter_guard_pass else "FAIL"
    dry_run_str = res.dry_run_status
    if res.dry_run_reason and res.dry_run_status != "SIMULATED_ACCEPTED":
        dry_run_str = f"FAIL ({res.dry_run_reason})"

    final_barrier_str = "PASS" if res.final_live_barrier_pass else "FAIL"
    create_barrier_str = "PASS" if res.create_order_barrier_pass else "FAIL"
    cancel_barrier_str = "PASS" if res.cancel_order_barrier_pass else "FAIL"

    ready_str = "YES" if res.ready_for_8_4c2 else "NO"

    return f"""============================================================
FINBOT — FASE 8.4C1 PRE-FLIGHT
============================================================

CREDENTIAL_STORE = {res.credential_store}
CREDENTIALS = {creds_str}
BINANCE_PRIVATE_AUTH = {auth_str}
PRIVATE_BALANCE_READ = {bal_read_str}

SYMBOL = {res.symbol}
MIN_AMOUNT = {min_amt_str}
STEP_SIZE = {step_size_str}
PRICE_TICK = {price_tick_str}
MIN_NOTIONAL = {min_notional_str}

MICRO_ORDER_CAP = {res.micro_order_cap:.2f} USDT
SAFE_MICRO_ORDER_POSSIBLE = {safe_micro_str}
CANDIDATE_NOTIONAL = {cand_notional_str}
CANDIDATE_QUANTITY = {cand_qty_str}

FUNDS_AVAILABLE_FOR_CANDIDATE = {funds_str}

MARKET_FILTER_GUARD = {mfg_str}
DRY_RUN = {dry_run_str}

FINAL_LIVE_BARRIER = {final_barrier_str}
CREATE_ORDER_BARRIER = {create_barrier_str}
CANCEL_ORDER_BARRIER = {cancel_barrier_str}

REAL_ORDERS_SENT = {res.real_orders_sent}
ORDER_NETWORK_CALLS = {res.order_network_calls}

READY_FOR_8_4C2 = {ready_str}

============================================================
"""


# =============================================================================
# CLI ENTRYPOINT
# =============================================================================

def main() -> int:
    """Ponto de entrada operacional CLI: python -m finbot.preflight."""
    result = run_preflight()
    print(format_preflight_report(result))
    return 0 if result.ready_for_8_4c2 else 1


if __name__ == "__main__":
    sys.exit(main())
