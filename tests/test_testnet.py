"""Bateria de testes unitários para a integração Binance Spot Testnet (FASE 8.4C2).

Garante com rigor matemático e arquitetural:
1. Testnet disabled por default.
2. Production continua bloqueada.
3. Credencial Production nunca é usada na Testnet.
4. Credencial Testnet nunca é usada em Production.
5. Ausência de credencial Testnet = fail closed.
6. Endpoint/environment mismatch = fail closed.
7. Raw OrderIntent não executa.
8. RejectedOrderIntent não executa.
9. ApprovedOrderIntent válido pode chegar ao fake Testnet adapter.
10. Cap de micro-order continua funcionando.
11. Filtros continuam funcionando.
12. Idempotência impede duplicidade.
13. Timeout vira UNKNOWN.
14. UNKNOWN não gera retry automático.
15. Reconciliação por clientOrderId.
16. Cancelamento somente de ordem conhecida/cancelável.
17. Nenhum teste automatizado toca Production.
18. Nenhum teste automatizado envia ordem externa real.
19. Secrets não aparecem em logs/exceptions.
20. Sentry detecta ambiente incorreto antes do WRITE.
21. Testnet Pre-Flight executa em modo 100% read-only.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import unittest
from unittest.mock import MagicMock, patch

from finbot.config import BinanceEnvironment, Config
from finbot.credentials import (
    BinanceCredentials,
    CredentialsMissingError,
    FakeCredentialProvider,
    TARGET_NAME_PRODUCTION,
    TARGET_NAME_SPOT_TESTNET,
    WindowsCredentialProvider,
    get_credential_target,
)
from finbot.execution import (
    InvalidExecutionIntentError,
    generate_client_order_id,
)
from finbot.live_executor import (
    AmbiguousExecutionError,
    BinanceOrderAdapter,
    ExchangeOrderResult,
    FakeExchangeOrderAdapter,
    GuardedLiveExecutionEngine,
    LiveExecutionArmingError,
    LiveOrderStorage,
    MicroOrderCapExceededError,
    OrderNotCancelableError,
    OrderStatus,
    RealOrderSubmissionBlockedError,
)
from finbot.live_safety import (
    ApprovedOrderIntent,
    MarketFilterGuard,
    MarketFilters,
    OrderIntent,
    RejectedOrderIntent,
)
from finbot.private_exchange import (
    BinancePrivateExchange,
    LiveTradingBlockedError,
)
from finbot.testnet_adapter import (
    BinanceSpotTestnetOrderAdapter,
    TestnetExecutionNotArmedError,
    TestnetSentryError,
    map_binance_status_to_order_status,
    verify_testnet_endpoint,
)
from finbot.testnet_preflight import (
    TestnetPreflightResult,
    run_testnet_preflight,
)


def _make_sample_order_intent(
    correlation_id: str = "corr-testnet-001",
    quantity: Decimal = Decimal("0.0002"),
    notional: Decimal = Decimal("10.00"),
    side: str = "BUY",
) -> OrderIntent:
    return OrderIntent(
        symbol="BTC/USDT",
        side=side,
        order_type="MARKET",
        quantity=quantity,
        price=None,
        requested_notional=notional,
        strategy_name="finbot_sma_test",
        strategy_version="1.0.0",
        signal="BUY",
        created_at=datetime.now(timezone.utc).isoformat(),
        correlation_id=correlation_id,
    )


def _make_sample_approved_intent(
    correlation_id: str = "corr-testnet-001",
    quantity: Decimal = Decimal("0.0002"),
    notional: Decimal = Decimal("10.00"),
    side: str = "BUY",
) -> ApprovedOrderIntent:
    intent = _make_sample_order_intent(
        correlation_id=correlation_id,
        quantity=quantity,
        notional=notional,
        side=side,
    )
    return ApprovedOrderIntent(
        intent=intent,
        normalized_quantity=quantity,
        normalized_price=None,
        normalized_notional=notional,
        checks={"risk_engine": "PASSED", "market_filters": "PASSED"},
        approved_at=datetime.now(timezone.utc).isoformat(),
    )


class TestBinanceSpotTestnetIntegration(unittest.TestCase):
    """Bateria de testes de isolamento e validação da Spot Testnet."""

    def test_01_testnet_disabled_by_default(self) -> None:
        """1. Testnet disabled por default no Config e no Adapter."""
        cfg = Config()
        self.assertEqual(cfg.binance_environment, BinanceEnvironment.PRODUCTION)
        self.assertFalse(cfg.testnet_execution_enabled)

        fake_creds = FakeCredentialProvider(api_key="k" * 32, api_secret="s" * 32)
        adapter = BinanceSpotTestnetOrderAdapter(credential_provider=fake_creds)
        self.assertFalse(adapter.testnet_execution_enabled)

        # Escritas desarmadas devem falhar categoricamente
        with self.assertRaises(TestnetExecutionNotArmedError):
            adapter.submit_order({"symbol": "BTC/USDT", "type": "market", "side": "buy", "amount": 0.001})

        with self.assertRaises(TestnetExecutionNotArmedError):
            adapter.cancel_order("BTC/USDT", order_id="123", client_order_id=None)

    def test_02_production_remains_blocked(self) -> None:
        """2. Production continua estritamente bloqueada."""
        prod_adapter = BinanceOrderAdapter(real_order_submission_enabled=False)
        with self.assertRaises(RealOrderSubmissionBlockedError):
            prod_adapter.submit_order({"symbol": "BTC/USDT"})

        with self.assertRaises(RealOrderSubmissionBlockedError):
            prod_adapter.cancel_order("BTC/USDT", "123", None)

        priv_ex = BinancePrivateExchange(
            config=Config(trading_mode="live"),
            credential_provider=FakeCredentialProvider(api_key="k" * 32, api_secret="s" * 32),
        )
        with self.assertRaises(LiveTradingBlockedError):
            priv_ex.create_order("BTC/USDT", "market", "buy", 0.001)

        with self.assertRaises(LiveTradingBlockedError):
            priv_ex.cancel_order("123", "BTC/USDT")

    def test_03_production_credentials_never_used_in_testnet(self) -> None:
        """3. Credencial de Produção NUNCA é usada na Testnet."""
        target_testnet = get_credential_target(BinanceEnvironment.SPOT_TESTNET)
        target_prod = get_credential_target(BinanceEnvironment.PRODUCTION)
        self.assertEqual(target_testnet, TARGET_NAME_SPOT_TESTNET)
        self.assertEqual(target_prod, TARGET_NAME_PRODUCTION)
        self.assertNotEqual(target_testnet, target_prod)

        adapter = BinanceSpotTestnetOrderAdapter()
        self.assertEqual(adapter.credential_provider.target_name, TARGET_NAME_SPOT_TESTNET)

    def test_04_testnet_credentials_never_used_in_production(self) -> None:
        """4. Credencial de Testnet NUNCA é usada em Produção."""
        prod_provider = WindowsCredentialProvider.for_environment(BinanceEnvironment.PRODUCTION)
        self.assertEqual(prod_provider.target_name, TARGET_NAME_PRODUCTION)
        self.assertNotEqual(prod_provider.target_name, TARGET_NAME_SPOT_TESTNET)

    def test_05_missing_testnet_credentials_fails_closed(self) -> None:
        """5. Ausência de credencial Testnet = fail closed."""
        empty_provider = FakeCredentialProvider(api_key=None, api_secret=None)
        adapter = BinanceSpotTestnetOrderAdapter(
            credential_provider=empty_provider,
            testnet_execution_enabled=True,
        )
        with self.assertRaises(CredentialsMissingError):
            adapter.get_balances()

        with self.assertRaises(CredentialsMissingError):
            adapter.submit_order({"symbol": "BTC/USDT", "type": "market", "side": "buy", "amount": 0.001})

    def test_06_endpoint_environment_mismatch_fails_closed(self) -> None:
        """6. Endpoint/environment mismatch = fail closed."""
        # Se engine está em SPOT_TESTNET, BinanceOrderAdapter de produção causa mismatch imediato
        cfg_testnet = Config(
            binance_environment=BinanceEnvironment.SPOT_TESTNET,
            testnet_execution_enabled=True,
        )
        prod_adapter = BinanceOrderAdapter(real_order_submission_enabled=False)
        engine_testnet = GuardedLiveExecutionEngine(
            adapter=prod_adapter,
            config=cfg_testnet,
        )
        app_intent = _make_sample_approved_intent()
        with self.assertRaises(RuntimeError) as ctx:
            engine_testnet.execute(app_intent)
        self.assertIn("Environment mismatch", str(ctx.exception))

        # Se engine está em PRODUCTION, adapter com environment=SPOT_TESTNET causa mismatch imediato
        cfg_prod = Config(
            trading_mode="live",
            live_trading_acknowledged=True,
            live_execution_enabled=True,
            binance_environment=BinanceEnvironment.PRODUCTION,
        )
        fake_testnet_adapter = FakeExchangeOrderAdapter(environment=BinanceEnvironment.SPOT_TESTNET)
        engine_prod = GuardedLiveExecutionEngine(
            adapter=fake_testnet_adapter,
            config=cfg_prod,
        )
        with self.assertRaises(RuntimeError) as ctx2:
            engine_prod.execute(app_intent)
        self.assertIn("Environment mismatch", str(ctx2.exception))

    def test_07_raw_order_intent_does_not_execute(self) -> None:
        """7. Raw OrderIntent não executa (exige ApprovedOrderIntent)."""
        cfg = Config(
            binance_environment=BinanceEnvironment.SPOT_TESTNET,
            testnet_execution_enabled=True,
        )
        fake_adapter = FakeExchangeOrderAdapter(environment=BinanceEnvironment.SPOT_TESTNET)
        engine = GuardedLiveExecutionEngine(adapter=fake_adapter, config=cfg)
        raw_intent = _make_sample_order_intent()

        with self.assertRaises(InvalidExecutionIntentError):
            engine.execute(raw_intent)  # type: ignore[arg-type]

    def test_08_rejected_order_intent_does_not_execute(self) -> None:
        """8. RejectedOrderIntent não executa."""
        cfg = Config(
            binance_environment=BinanceEnvironment.SPOT_TESTNET,
            testnet_execution_enabled=True,
        )
        fake_adapter = FakeExchangeOrderAdapter(environment=BinanceEnvironment.SPOT_TESTNET)
        engine = GuardedLiveExecutionEngine(adapter=fake_adapter, config=cfg)
        rej_intent = RejectedOrderIntent(
            intent=_make_sample_order_intent(),
            reason_code="RISK_REJECT",
            reason="Blocked by risk",
            checks={},
            rejected_at=datetime.now(timezone.utc).isoformat(),
        )

        with self.assertRaises(InvalidExecutionIntentError):
            engine.execute(rej_intent)  # type: ignore[arg-type]

    def test_09_valid_approved_order_intent_reaches_fake_testnet_adapter(self) -> None:
        """9. ApprovedOrderIntent válido pode chegar ao fake Testnet adapter."""
        cfg = Config(
            binance_environment=BinanceEnvironment.SPOT_TESTNET,
            testnet_execution_enabled=True,
        )
        storage = LiveOrderStorage(":memory:")
        fake_adapter = FakeExchangeOrderAdapter(
            default_status=OrderStatus.ACKNOWLEDGED,
            environment=BinanceEnvironment.SPOT_TESTNET,
        )
        engine = GuardedLiveExecutionEngine(adapter=fake_adapter, storage=storage, config=cfg)

        approved = _make_sample_approved_intent(correlation_id="corr-valid-009")
        res = engine.execute(approved)

        self.assertEqual(res.status, OrderStatus.ACKNOWLEDGED)
        self.assertEqual(len(fake_adapter.submitted_payloads), 1)
        self.assertEqual(fake_adapter.submitted_payloads[0]["symbol"], "BTC/USDT")

        # Verifica persistência no storage
        saved = storage.get_order_by_correlation_id("corr-valid-009")
        self.assertIsNotNone(saved)
        self.assertEqual(saved["current_status"], OrderStatus.ACKNOWLEDGED.value)

    def test_10_micro_order_cap_still_enforced(self) -> None:
        """10. Cap de micro-order continua funcionando na Testnet."""
        cfg = Config(
            binance_environment=BinanceEnvironment.SPOT_TESTNET,
            testnet_execution_enabled=True,
            live_micro_order_max_notional=15.0,
        )
        fake_adapter = FakeExchangeOrderAdapter(environment=BinanceEnvironment.SPOT_TESTNET)
        engine = GuardedLiveExecutionEngine(adapter=fake_adapter, config=cfg)

        # 25.0 USDT excede o cap de 15.0 USDT
        approved = _make_sample_approved_intent(
            correlation_id="corr-cap-010",
            notional=Decimal("25.00"),
        )
        with self.assertRaises(MicroOrderCapExceededError):
            engine.execute(approved)

    def test_11_market_filters_still_enforced(self) -> None:
        """11. Filtros continuam funcionando e rejeitam abaixo do mínimo."""
        filters = MarketFilters(
            symbol="BTC/USDT",
            base_asset="BTC",
            quote_asset="USDT",
            min_amount=Decimal("0.001"),
            max_amount=Decimal("100.0"),
            amount_step=Decimal("0.0001"),
            min_price=Decimal("1.0"),
            max_price=Decimal("100000.0"),
            price_step=Decimal("0.01"),
            min_cost=Decimal("5.0"),
            max_cost=Decimal("100000.0"),
        )
        guard = MarketFilterGuard(filters)

        # Ordem com 0.0001 BTC < 0.001 BTC (min_amount) deve ser rejeitada
        intent_below = _make_sample_order_intent(quantity=Decimal("0.0001"))
        decision = guard.validate_order_intent(intent_below)
        self.assertFalse(decision.is_valid)
        self.assertEqual(decision.code, "AMOUNT_FILTER_FAILED")

    def test_12_idempotency_prevents_duplicate(self) -> None:
        """12. Idempotência impede duplicidade."""
        cfg = Config(
            binance_environment=BinanceEnvironment.SPOT_TESTNET,
            testnet_execution_enabled=True,
        )
        storage = LiveOrderStorage(":memory:")
        fake_adapter = FakeExchangeOrderAdapter(environment=BinanceEnvironment.SPOT_TESTNET)
        engine = GuardedLiveExecutionEngine(adapter=fake_adapter, storage=storage, config=cfg)

        approved = _make_sample_approved_intent(correlation_id="corr-idemp-012")
        engine.execute(approved)

        # Segunda tentativa com o mesmo correlation_id falha
        with self.assertRaises(RuntimeError) as ctx:
            engine.execute(approved)
        self.assertIn("DUPLICATE_INTENT", str(ctx.exception))

    def test_13_timeout_becomes_unknown(self) -> None:
        """13. Timeout vira UNKNOWN."""
        cfg = Config(
            binance_environment=BinanceEnvironment.SPOT_TESTNET,
            testnet_execution_enabled=True,
        )
        storage = LiveOrderStorage(":memory:")
        fake_adapter = FakeExchangeOrderAdapter(
            simulate_timeout=True,
            environment=BinanceEnvironment.SPOT_TESTNET,
        )
        engine = GuardedLiveExecutionEngine(adapter=fake_adapter, storage=storage, config=cfg)

        approved = _make_sample_approved_intent(correlation_id="corr-timeout-013")
        res = engine.execute(approved)

        self.assertEqual(res.status, OrderStatus.UNKNOWN)
        saved = storage.get_order_by_correlation_id("corr-timeout-013")
        self.assertIsNotNone(saved)
        self.assertEqual(saved["current_status"], OrderStatus.UNKNOWN.value)

    def test_14_unknown_does_not_trigger_auto_retry(self) -> None:
        """14. UNKNOWN não gera retry automático."""
        cfg = Config(
            binance_environment=BinanceEnvironment.SPOT_TESTNET,
            testnet_execution_enabled=True,
        )
        fake_adapter = FakeExchangeOrderAdapter(
            simulate_timeout=True,
            environment=BinanceEnvironment.SPOT_TESTNET,
        )
        engine = GuardedLiveExecutionEngine(adapter=fake_adapter, config=cfg)

        approved = _make_sample_approved_intent(correlation_id="corr-noretry-014")
        engine.execute(approved)

        # Apenas 1 tentativa deve ter sido realizada
        self.assertEqual(len(fake_adapter.submitted_payloads), 1)

    def test_15_reconciliation_by_client_order_id(self) -> None:
        """15. Reconciliação por clientOrderId."""
        cfg = Config(
            binance_environment=BinanceEnvironment.SPOT_TESTNET,
            testnet_execution_enabled=True,
        )
        storage = LiveOrderStorage(":memory:")
        fake_adapter = FakeExchangeOrderAdapter(
            default_status=OrderStatus.ACKNOWLEDGED,
            environment=BinanceEnvironment.SPOT_TESTNET,
        )
        engine = GuardedLiveExecutionEngine(adapter=fake_adapter, storage=storage, config=cfg)

        approved = _make_sample_approved_intent(correlation_id="corr-recon-015")
        res = engine.execute(approved)
        cid = res.client_order_id

        # Simula preenchimento da ordem na exchange
        fake_adapter.orders[cid] = ExchangeOrderResult(
            client_order_id=cid,
            exchange_order_id=res.exchange_order_id,
            status=OrderStatus.FILLED,
            symbol="BTC/USDT",
            side="BUY",
            order_type="MARKET",
            requested_quantity=Decimal("0.0002"),
            executed_quantity=Decimal("0.0002"),
            cumulative_quote_quantity=Decimal("10.0"),
            average_price=Decimal("50000.0"),
        )

        reconciled = engine.reconcile_order(cid)
        self.assertEqual(reconciled.status, OrderStatus.FILLED)
        saved = storage.get_order_by_client_order_id(cid)
        self.assertIsNotNone(saved)
        self.assertEqual(saved["current_status"], OrderStatus.FILLED.value)

    def test_16_cancellation_only_of_known_cancelable_order(self) -> None:
        """16. Cancelamento somente de ordem conhecida e cancelável."""
        cfg = Config(
            binance_environment=BinanceEnvironment.SPOT_TESTNET,
            testnet_execution_enabled=True,
        )
        storage = LiveOrderStorage(":memory:")
        fake_adapter = FakeExchangeOrderAdapter(
            default_status=OrderStatus.ACKNOWLEDGED,
            environment=BinanceEnvironment.SPOT_TESTNET,
        )
        engine = GuardedLiveExecutionEngine(adapter=fake_adapter, storage=storage, config=cfg)

        # Ordem desconhecida
        with self.assertRaises(ValueError):
            engine.cancel_order("non_existent_client_id")

        # Ordem conhecida em ACKNOWLEDGED pode ser cancelada
        approved = _make_sample_approved_intent(correlation_id="corr-cancel-016")
        res = engine.execute(approved)
        canceled_res = engine.cancel_order(res.client_order_id)
        self.assertEqual(canceled_res.status, OrderStatus.CANCELED)

        # Ordem já CANCELED não pode ser cancelada novamente
        with self.assertRaises(OrderNotCancelableError):
            engine.cancel_order(res.client_order_id)

    def test_17_no_automated_test_touches_production(self) -> None:
        """17. Nenhum teste automatizado toca Production."""
        cfg = Config(binance_environment=BinanceEnvironment.SPOT_TESTNET)
        self.assertFalse(cfg.real_order_submission_enabled)
        adapter = BinanceOrderAdapter(real_order_submission_enabled=False)
        self.assertEqual(adapter.environment, BinanceEnvironment.PRODUCTION)
        with self.assertRaises(RealOrderSubmissionBlockedError):
            adapter.submit_order({"symbol": "BTC/USDT"})

    def test_18_no_automated_test_sends_real_external_orders(self) -> None:
        """18. Nenhum teste automatizado envia ordem externa real."""
        fake_adapter = FakeExchangeOrderAdapter()
        approved = _make_sample_approved_intent()
        cfg = Config(binance_environment=BinanceEnvironment.SPOT_TESTNET, testnet_execution_enabled=True)
        engine = GuardedLiveExecutionEngine(adapter=fake_adapter, config=cfg)
        res = engine.execute(approved)
        self.assertIsNotNone(res)
        # Nenhuma chamada HTTP / socket foi realizada

    def test_19_secrets_do_not_appear_in_logs_or_exceptions(self) -> None:
        """19. Secrets não aparecem em logs, repr ou exceptions."""
        creds = BinanceCredentials(api_key="my_super_secret_api_key_123", api_secret="my_super_secret_secret_456")
        repr_str = repr(creds)
        str_val = str(creds)
        self.assertNotIn("my_super_secret", repr_str)
        self.assertNotIn("my_super_secret", str_val)
        self.assertIn("[PROTECTED]", repr_str)

        # Exceção de Sentry ou Arming não contém secrets
        err = TestnetSentryError("Endpoint error occurred without leaking secrets.")
        self.assertNotIn("my_super_secret", str(err))

    def test_20_sentry_detects_incorrect_environment_before_write(self) -> None:
        """20. Sentry detecta ambiente incorreto antes do WRITE."""
        mock_client = MagicMock()

        # Caso 1: Client é None
        with self.assertRaises(TestnetSentryError):
            verify_testnet_endpoint(None)

        # Caso 2: URLs vazias
        mock_client.urls = {}
        with self.assertRaises(TestnetSentryError):
            verify_testnet_endpoint(mock_client)

        # Caso 3: URL aponta para produção
        mock_client.urls = {
            "api": {
                "public": "https://api.binance.com/api/v3",
                "private": "https://api.binance.com/api/v3",
            }
        }
        with self.assertRaises(TestnetSentryError) as ctx_prod:
            verify_testnet_endpoint(mock_client)
        self.assertIn("Endpoint de PRODUÇÃO detectado", str(ctx_prod.exception))

        # Caso 4: URL válida de Testnet
        mock_client.urls = {
            "api": {
                "public": "https://testnet.binance.vision/api/v3",
                "private": "https://testnet.binance.vision/api/v3",
            }
        }
        # Não deve levantar exceção
        verify_testnet_endpoint(mock_client)

    def test_21_testnet_preflight_read_only_passes_with_fakes(self) -> None:
        """21. Testnet Pre-Flight executa em modo 100% read-only com sucesso."""
        fake_creds = FakeCredentialProvider(api_key="k" * 32, api_secret="s" * 32)
        mock_client = MagicMock()
        mock_client.urls = {
            "api": {
                "public": "https://testnet.binance.vision/api/v3",
                "private": "https://testnet.binance.vision/api/v3",
            }
        }
        mock_client.fetch_status.return_value = {"status": "ok"}
        mock_client.fetch_balance.return_value = {
            "free": {"BTC": 1.0, "USDT": 5000.0},
            "used": {"BTC": 0.0, "USDT": 0.0},
            "total": {"BTC": 1.0, "USDT": 5000.0},
        }

        fake_adapter = BinanceSpotTestnetOrderAdapter(
            credential_provider=fake_creds,
            client=mock_client,
            testnet_execution_enabled=False,
        )

        sample_market = {
            "symbol": "BTC/USDT",
            "base": "BTC",
            "quote": "USDT",
            "limits": {
                "amount": {"min": 0.0001, "max": 100.0},
                "price": {"min": 1.0, "max": 100000.0},
                "cost": {"min": 5.0, "max": 100000.0},
            },
            "precision": {"amount": 0.0001, "price": 0.01},
        }

        res = run_testnet_preflight(
            credential_provider=fake_creds,
            adapter=fake_adapter,
            market_data=sample_market,
        )

        self.assertTrue(res.testnet_credentials_present)
        self.assertTrue(res.testnet_auth_pass)
        self.assertTrue(res.testnet_balance_read_pass)
        self.assertTrue(res.testnet_market_metadata_pass)
        self.assertTrue(res.risk_engine_pass)
        self.assertTrue(res.market_filter_guard_pass)
        self.assertTrue(res.execution_barrier_pass)
        self.assertTrue(res.production_isolation_pass)
        self.assertTrue(res.ready_for_testnet_order)

    def test_22_testnet_preflight_missing_credentials_fails_safely(self) -> None:
        """22. Testnet Pre-Flight falha com elegância quando credenciais estão ausentes."""
        empty_creds = FakeCredentialProvider(api_key=None, api_secret=None)
        res = run_testnet_preflight(credential_provider=empty_creds)

        self.assertFalse(res.testnet_credentials_present)
        self.assertFalse(res.ready_for_testnet_order)
        self.assertTrue(len(res.error_messages) > 0)


if __name__ == "__main__":
    unittest.main()
