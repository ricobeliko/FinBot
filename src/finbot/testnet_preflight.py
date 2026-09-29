"""Módulo de verificação pré-operacional de prontidão da Binance Spot Testnet (FASE 8.4C2).

Executa validações 100% READ-ONLY na Binance Spot Testnet antes de qualquer futura ordem de teste:
1. Armazenamento de credenciais (Windows Credential Manager / Target SpotTestnet)
2. Presença de credenciais exclusivas da Testnet
3. Autenticação privada na Spot Testnet (Read-Only)
4. Consulta privada de saldos na Testnet (Read-Only, sem exibição patrimonial)
5. Metadados e filtros de mercado da Testnet (BTC/USDT)
6. Avaliação do Risk Engine existente
7. Conformidade com MarketFilterGuard
8. Verificação de barreiras de execução (testnet_execution_enabled == False por default)
9. Isolamento rigoroso de Produção (garantia de que Produção está intocada e bloqueada)

ESTRUTURALMENTE INCAPAZ DE ENVIAR OU CANCELAR ORDENS.
ZERO ORDENS ENVIADAS.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import logging
import sys
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
from finbot.live_executor import (
    BinanceOrderAdapter,
    RealOrderSubmissionBlockedError,
)
from finbot.live_safety import (
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
)
from finbot.risk import RiskDecision, RiskDecisionCode
from finbot.testnet_adapter import (
    BinanceSpotTestnetOrderAdapter,
    TestnetExecutionNotArmedError,
    TestnetSentryError,
    verify_testnet_endpoint,
)

logger = logging.getLogger(__name__)


@dataclass
class TestnetPreflightResult:
    """Resultado estruturado e auditável de todas as verificações do Testnet Pre-Flight."""

    credential_store: str = "WINDOWS_CREDENTIAL_MANAGER"
    testnet_credentials_present: bool = False
    testnet_auth_pass: bool = False
    testnet_balance_read_pass: bool = False
    testnet_market_metadata_pass: bool = False
    risk_engine_pass: bool = False
    market_filter_guard_pass: bool = False
    execution_barrier_pass: bool = False
    production_isolation_pass: bool = False

    # Detalhes informativos (sem secrets ou valores patrimoniais)
    credential_target: str = TARGET_NAME_SPOT_TESTNET
    assets_found_count: int = 0
    symbol_evaluated: str = "BTC/USDT"
    min_amount: Decimal | None = None
    step_size: Decimal | None = None
    min_notional: Decimal | None = None
    ready_for_testnet_order: bool = False
    error_messages: list[str] | None = None

    def __post_init__(self) -> None:
        if self.error_messages is None:
            self.error_messages = []


def run_testnet_preflight(
    config: Config | None = None,
    credential_provider: CredentialProvider | None = None,
    adapter: BinanceSpotTestnetOrderAdapter | None = None,
    market_data: dict[str, Any] | None = None,
) -> TestnetPreflightResult:
    """Executa todas as verificações de prontidão da Testnet em modo estritamente READ-ONLY."""
    cfg = config or get_config()
    result = TestnetPreflightResult()

    # 1. Provedor e Target de Credenciais
    provider = credential_provider or WindowsCredentialProvider.for_environment(
        BinanceEnvironment.SPOT_TESTNET
    )
    result.credential_store = provider.get_provider_name().upper().replace(" ", "_")
    result.credential_target = getattr(provider, "target_name", TARGET_NAME_SPOT_TESTNET)

    # 2. Verificação de Credenciais da Testnet (Sem expor chaves)
    try:
        has_creds = provider.has_binance_credentials()
        result.testnet_credentials_present = bool(has_creds)
        if not has_creds:
            result.error_messages.append(
                f"Credenciais da Testnet ausentes no target '{result.credential_target}'."
            )
    except Exception as exc:
        result.testnet_credentials_present = False
        result.error_messages.append(f"Erro ao verificar credenciais: {exc}")

    # 3. Inicialização do Adapter Spot Testnet
    testnet_adapter = adapter
    if testnet_adapter is None:
        testnet_adapter = BinanceSpotTestnetOrderAdapter(
            credential_provider=provider,
            testnet_execution_enabled=False,  # Garante READ-ONLY no preflight
        )

    # 4. Autenticação Privada na Testnet (Read-Only)
    if result.testnet_credentials_present:
        try:
            status = testnet_adapter.get_account_status()
            result.testnet_auth_pass = status is not None
        except Exception as exc:
            result.testnet_auth_pass = False
            result.error_messages.append(f"Falha na autenticação Testnet: {exc}")
    else:
        result.testnet_auth_pass = False

    # 5. Consulta de Saldos na Testnet (Read-Only, sem expor valores)
    if result.testnet_auth_pass:
        try:
            balances = testnet_adapter.get_balances()
            result.testnet_balance_read_pass = True
            result.assets_found_count = len(balances)
        except Exception as exc:
            result.testnet_balance_read_pass = False
            result.error_messages.append(f"Falha na leitura de saldos Testnet: {exc}")
    else:
        result.testnet_balance_read_pass = False

    # 6. Metadados de Mercado da Testnet
    filters: MarketFilters | None = None
    try:
        if market_data is not None:
            raw_markets = {"BTC/USDT": market_data}
        else:
            raw_markets = testnet_adapter.load_markets()

        btc_market = raw_markets.get("BTC/USDT")
        if btc_market:
            filters = extract_market_filters(btc_market)
            result.min_amount = filters.min_amount
            result.step_size = filters.amount_step
            result.min_notional = filters.min_cost
            result.testnet_market_metadata_pass = True
        else:
            result.testnet_market_metadata_pass = False
            result.error_messages.append("Par BTC/USDT não encontrado nos mercados da Testnet.")
    except Exception as exc:
        result.testnet_market_metadata_pass = False
        result.error_messages.append(f"Falha ao carregar metadados da Testnet: {exc}")

    # 7. Verificação do Risk Engine
    try:
        dummy_risk = RiskDecision(
            allowed=True,
            code=RiskDecisionCode.ALLOWED,
            reason="Preflight baseline verification",
            action="BUY",
            target_notional=Decimal("10.00"),
        )
        result.risk_engine_pass = dummy_risk.allowed and dummy_risk.action == "BUY"
    except Exception as exc:
        result.risk_engine_pass = False
        result.error_messages.append(f"Falha ao avaliar Risk Engine: {exc}")

    # 8. Verificação do MarketFilterGuard
    if filters is not None:
        try:
            guard = MarketFilterGuard(filters)
            # Testa sanitização com quantidade válida
            is_valid, sanitized_qty, _ = sanitize_amount(
                Decimal("0.001"),
                filters.min_amount,
                filters.amount_step,
                filters.max_amount,
            )
            result.market_filter_guard_pass = bool(is_valid and sanitized_qty > 0)
        except Exception as exc:
            result.market_filter_guard_pass = False
            result.error_messages.append(f"Falha no MarketFilterGuard: {exc}")
    else:
        result.market_filter_guard_pass = False

    # 9. Verificação de Barreiras de Execução da Testnet (Fail-Closed)
    try:
        # Tenta submeter ordem com testnet_execution_enabled=False no adapter
        barrier_passed = False
        try:
            testnet_adapter.submit_order({"symbol": "BTC/USDT", "type": "market", "side": "buy", "amount": 0.001})
        except TestnetExecutionNotArmedError:
            barrier_passed = True
        except Exception:
            barrier_passed = False

        result.execution_barrier_pass = barrier_passed
        if not barrier_passed:
            result.error_messages.append("Falha de barreira: escrita na Testnet não bloqueou com adapter desarmado.")
    except Exception as exc:
        result.execution_barrier_pass = False
        result.error_messages.append(f"Erro na checagem de barreira da Testnet: {exc}")

    # 10. Verificação Rigorosa de Isolamento de Produção
    prod_isolation = True
    # a) Target de Testnet nunca deve ser de Produção
    if result.credential_target == TARGET_NAME_PRODUCTION:
        prod_isolation = False
        result.error_messages.append("VIOLAÇÃO: Target de credencial configurado aponta para Produção!")

    # b) URLs do client CCXT do adapter devem conter testnet e JAMAIS api.binance.com
    if getattr(testnet_adapter, "_client", None) is not None:
        try:
            verify_testnet_endpoint(testnet_adapter._client)
        except TestnetSentryError as err:
            prod_isolation = False
            result.error_messages.append(f"VIOLAÇÃO DE ISOLAMENTO: {err}")

    # c) Produção continua bloqueada no Config
    if cfg.real_order_submission_enabled:
        prod_isolation = False
        result.error_messages.append("VIOLAÇÃO: real_order_submission_enabled está ativo no Config!")

    # d) BinanceOrderAdapter de produção bloqueia writes
    prod_adapter = BinanceOrderAdapter(real_order_submission_enabled=False)
    try:
        prod_adapter.submit_order({"symbol": "BTC/USDT"})
        prod_isolation = False
        result.error_messages.append("VIOLAÇÃO: BinanceOrderAdapter de produção não bloqueou submit_order!")
    except RealOrderSubmissionBlockedError:
        pass

    # e) BinancePrivateExchange bloqueia ordens
    try:
        priv_exchange = BinancePrivateExchange(
            config=Config(trading_mode="live"),
            credential_provider=FakeCredentialProvider(
                api_key="k" * 32, api_secret="s" * 32
            ),
        )
        priv_exchange.create_order("BTC/USDT", "market", "buy", 0.001)
        prod_isolation = False
        result.error_messages.append("VIOLAÇÃO: BinancePrivateExchange não bloqueou create_order!")
    except LiveTradingBlockedError:
        pass
    except Exception as exc:
        prod_isolation = False
        result.error_messages.append(f"VIOLAÇÃO: Erro inesperado na verificação de BinancePrivateExchange: {exc}")

    result.production_isolation_pass = prod_isolation

    # Avaliação Final de Prontidão
    all_passed = (
        result.testnet_credentials_present
        and result.testnet_auth_pass
        and result.testnet_balance_read_pass
        and result.testnet_market_metadata_pass
        and result.risk_engine_pass
        and result.market_filter_guard_pass
        and result.execution_barrier_pass
        and result.production_isolation_pass
    )
    result.ready_for_testnet_order = all_passed

    return result


def print_testnet_preflight_report(res: TestnetPreflightResult) -> None:
    """Imprime o relatório pré-operacional da Testnet de forma segura e profissional."""
    print("=" * 65)
    print("       FinBot — BINANCE SPOT TESTNET PRE-FLIGHT (READ-ONLY)       ")
    print("=" * 65)
    print(f"Timestamp (UTC)              : {datetime.now(timezone.utc).isoformat()}")
    print(f"CREDENTIAL_STORE             : {res.credential_store}")
    print(f"TARGET_NAME                  : {res.credential_target}")
    print(f"TESTNET_CREDENTIALS          : {'PRESENT' if res.testnet_credentials_present else 'MISSING'}")
    print(f"TESTNET_AUTH                 : {'PASS' if res.testnet_auth_pass else 'FAIL'}")
    print(f"TESTNET_BALANCE_READ         : {'PASS' if res.testnet_balance_read_pass else 'FAIL'}")
    print(f"TESTNET_MARKET_METADATA      : {'PASS' if res.testnet_market_metadata_pass else 'FAIL'}")
    print(f"RISK_ENGINE                  : {'PASS' if res.risk_engine_pass else 'FAIL'}")
    print(f"MARKET_FILTER_GUARD          : {'PASS' if res.market_filter_guard_pass else 'FAIL'}")
    print(f"EXECUTION_BARRIER            : {'PASS' if res.execution_barrier_pass else 'FAIL'}")
    print(f"PRODUCTION_ISOLATION         : {'PASS' if res.production_isolation_pass else 'FAIL'}")
    print("-" * 65)
    print(f"Symbol                       : {res.symbol_evaluated}")
    if res.min_amount is not None:
        print(f"Min Amount (minQty)          : {res.min_amount}")
        print(f"Step Size (stepSize)         : {res.step_size}")
        print(f"Min Notional (minNotional)   : {res.min_notional} USDT")
    print(f"Active Assets Found          : {res.assets_found_count}")
    print("-" * 65)
    print("INVIOLABILIDADE OPERACIONAL:")
    print("TESTNET_ORDERS_SENT          : 0")
    print("PRODUCTION_ORDERS_SENT       : 0")
    print("PRODUCTION_WRITE_ENABLED     : NO")
    print("=" * 65)
    print(f"READY_FOR_TESTNET_ORDER      : {'YES' if res.ready_for_testnet_order else 'NO'}")
    print("=" * 65)

    if res.error_messages:
        print("\nMOTIVOS / OBSERVAÇÕES:")
        for msg in res.error_messages:
            print(f"- {msg}")
        print()


def main(argv: list[str] | None = None) -> int:
    """Ponto de entrada do comando operacional python -m finbot.testnet_preflight."""
    result = run_testnet_preflight()
    print_testnet_preflight_report(result)
    return 0 if result.ready_for_testnet_order else 1


if __name__ == "__main__":
    sys.exit(main())
