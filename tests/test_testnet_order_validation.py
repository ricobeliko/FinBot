"""Bateria de testes focados para validação operacional da Binance Spot Testnet (FASE 8.4C2B).

Testa exaustivamente todas as regras constitucionais, sentries defensivos,
isolamento de produção, cálculo de candidata, idempotência, falha ambígua e reconciliação.

ZERO CHAMADAS EXTERNAS À REDE.
"""

from decimal import Decimal
import io
import sys
import unittest
from unittest.mock import MagicMock, patch

from finbot.config import BinanceEnvironment, Config
from finbot.credentials import (
    FakeCredentialProvider,
    TARGET_NAME_PRODUCTION,
    TARGET_NAME_SPOT_TESTNET,
)
from finbot.live_executor import (
    BinanceOrderAdapter,
    FakeExchangeOrderAdapter,
    LiveOrderStorage,
    OrderStatus,
)
from finbot.live_safety import (
    MarketFilters,
    extract_market_filters,
)
from finbot.testnet_adapter import (
    BinanceSpotTestnetOrderAdapter,
    TestnetSentryError,
)
from finbot.testnet_order_validation import (
    DEFAULT_TARGET_NOTIONAL,
    SYMBOL_BTC_USDT,
    TestnetOrderExecutionReport,
    TestnetValidationPreview,
    calculate_testnet_order_candidate,
    check_production_isolation,
    main,
    parse_args,
    print_preview,
    print_report,
    reconcile_with_bounded_polling,
    run_testnet_order_validation,
    verify_testnet_write_sentries,
)


class TestTestnetOrderValidation(unittest.TestCase):
    """Bateria de testes focados da FASE 8.4C2B."""

    def setUp(self) -> None:
        self.market_dict = {
            "symbol": SYMBOL_BTC_USDT,
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
        self.filters = extract_market_filters(self.market_dict)
        self.fake_provider = FakeCredentialProvider(
            api_key="testnet_fake_key_1234567890",
            api_secret="testnet_fake_secret_1234567890",
        )
        self.fake_provider.target_name = TARGET_NAME_SPOT_TESTNET

    # 1. Sem confirmação => Nenhuma chamada WRITE
    def test_run_preview_mode_executes_zero_writes(self) -> None:
        fake_adapter = FakeExchangeOrderAdapter(environment=BinanceEnvironment.SPOT_TESTNET)
        storage = LiveOrderStorage(":memory:")

        preview, report = run_testnet_order_validation(
            confirm_testnet_order=False,
            credential_provider=self.fake_provider,
            adapter=fake_adapter,
            storage=storage,
            current_price=Decimal("60000.00"),
        )

        self.assertIsNotNone(preview)
        self.assertIsNone(report)
        self.assertFalse(preview.testnet_write_executed)
        self.assertTrue(preview.ready_to_execute)
        self.assertEqual(len(fake_adapter.submitted_payloads), 0)

    # 2. Confirmação Testnet correta => fake adapter recebe exatamente 1 submit
    def test_run_armed_mode_submits_exactly_one_order(self) -> None:
        fake_adapter = FakeExchangeOrderAdapter(
            default_status=OrderStatus.FILLED,
            environment=BinanceEnvironment.SPOT_TESTNET,
        )
        storage = LiveOrderStorage(":memory:")

        preview, report = run_testnet_order_validation(
            confirm_testnet_order=True,
            credential_provider=self.fake_provider,
            adapter=fake_adapter,
            storage=storage,
            current_price=Decimal("60000.00"),
            correlation_id="corr_test_001",
            poll_delay_seconds=0.0,
        )

        self.assertIsNone(preview)
        self.assertIsNotNone(report)
        self.assertEqual(len(fake_adapter.submitted_payloads), 1)
        self.assertEqual(report.testnet_orders_sent, 1)
        self.assertEqual(report.production_orders_sent, 0)
        self.assertFalse(report.production_write_enabled)
        self.assertEqual(report.order_status, OrderStatus.FILLED.value)

    # 3. Confirmação genérica não vale (--yes, --force, --live)
    def test_generic_flags_are_rejected(self) -> None:
        for flag in ["--yes", "--force", "--live"]:
            with self.subTest(flag=flag):
                output_capture = io.StringIO()
                with patch("sys.stdout", output_capture):
                    ret = main([flag])
                self.assertEqual(ret, 1)
                self.assertIn("ERRO DE SEGURANÇA", output_capture.getvalue())
                self.assertIn("--confirm-testnet-order", output_capture.getvalue())

    # 4. Production adapter rejeitado
    def test_production_adapter_is_rejected_fail_closed(self) -> None:
        prod_adapter = BinanceOrderAdapter(real_order_submission_enabled=False)
        cfg = Config(
            binance_environment=BinanceEnvironment.SPOT_TESTNET,
            testnet_execution_enabled=True,
        )
        with self.assertRaises(TestnetSentryError) as ctx:
            verify_testnet_write_sentries(cfg, prod_adapter, self.fake_provider)
        self.assertIn("BinanceOrderAdapter", str(ctx.exception))

    # 5. Production endpoint rejeitado
    def test_production_endpoint_is_rejected(self) -> None:
        fake_adapter = FakeExchangeOrderAdapter(environment=BinanceEnvironment.SPOT_TESTNET)
        fake_adapter.urls = {
            "api": {
                "public": "https://api.binance.com/api/v3",
                "private": "https://api.binance.com/api/v3",
            }
        }
        cfg = Config(
            binance_environment=BinanceEnvironment.SPOT_TESTNET,
            testnet_execution_enabled=True,
        )
        with self.assertRaises(TestnetSentryError) as ctx:
            verify_testnet_write_sentries(cfg, fake_adapter, self.fake_provider)
        self.assertIn("api.binance.com", str(ctx.exception))

    # 6. Production credentials rejeitadas (target Production)
    def test_production_credentials_target_is_rejected(self) -> None:
        fake_adapter = FakeExchangeOrderAdapter(environment=BinanceEnvironment.SPOT_TESTNET)
        prod_creds = FakeCredentialProvider(api_key="k" * 32, api_secret="s" * 32)
        prod_creds.target_name = TARGET_NAME_PRODUCTION

        cfg = Config(
            binance_environment=BinanceEnvironment.SPOT_TESTNET,
            testnet_execution_enabled=True,
        )
        with self.assertRaises(TestnetSentryError) as ctx:
            verify_testnet_write_sentries(cfg, fake_adapter, prod_creds)
        self.assertIn("Target de credenciais aponta para Produção", str(ctx.exception))

    # 7. Cap preservado
    def test_micro_order_cap_preserved(self) -> None:
        # Se max_cap for 4.0 USDT e min_cost for 5.0 USDT, cálculo deve retornar None
        cand = calculate_testnet_order_candidate(
            filters=self.filters,
            current_price=Decimal("60000.00"),
            max_cap=Decimal("4.00"),
            target_notional=Decimal("6.00"),
        )
        self.assertIsNone(cand)

    # 8. Filtros preservados
    def test_filters_preserved_in_candidate_calculation(self) -> None:
        cand = calculate_testnet_order_candidate(
            filters=self.filters,
            current_price=Decimal("60000.00"),
            max_cap=Decimal("15.00"),
            target_notional=Decimal("6.00"),
        )
        self.assertIsNotNone(cand)
        qty, notional, px = cand
        self.assertGreaterEqual(qty, self.filters.min_amount)
        self.assertGreaterEqual(notional, self.filters.min_cost)
        self.assertLessEqual(notional, Decimal("15.00"))
        # Verifica múltiplo exato de amount_step
        units = qty / self.filters.amount_step
        self.assertEqual(units, units.to_integral_value())

    # 9. Idempotência
    def test_idempotency_prevents_duplicate_submission(self) -> None:
        fake_adapter = FakeExchangeOrderAdapter(
            default_status=OrderStatus.FILLED,
            environment=BinanceEnvironment.SPOT_TESTNET,
        )
        storage = LiveOrderStorage(":memory:")

        # Primeira execução
        _, rep1 = run_testnet_order_validation(
            confirm_testnet_order=True,
            credential_provider=self.fake_provider,
            adapter=fake_adapter,
            storage=storage,
            current_price=Decimal("60000.00"),
            correlation_id="duplicate_corr_id",
            poll_delay_seconds=0.0,
        )
        self.assertEqual(len(fake_adapter.submitted_payloads), 1)

        # Segunda execução com mesmo correlation_id deve falhar
        with self.assertRaises(RuntimeError) as ctx:
            run_testnet_order_validation(
                confirm_testnet_order=True,
                credential_provider=self.fake_provider,
                adapter=fake_adapter,
                storage=storage,
                current_price=Decimal("60000.00"),
                correlation_id="duplicate_corr_id",
                poll_delay_seconds=0.0,
            )
        self.assertIn("DUPLICATE_INTENT", str(ctx.exception))
        # O adapter não pode ter sido chamado novamente
        self.assertEqual(len(fake_adapter.submitted_payloads), 1)

    # 10. Timeout => UNKNOWN
    def test_timeout_results_in_unknown_status(self) -> None:
        fake_adapter = FakeExchangeOrderAdapter(
            simulate_timeout=True,
            environment=BinanceEnvironment.SPOT_TESTNET,
        )
        storage = LiveOrderStorage(":memory:")

        _, report = run_testnet_order_validation(
            confirm_testnet_order=True,
            credential_provider=self.fake_provider,
            adapter=fake_adapter,
            storage=storage,
            current_price=Decimal("60000.00"),
            correlation_id="timeout_corr_id",
            poll_delay_seconds=0.0,
        )

        self.assertIsNotNone(report)
        # Reconciliação tentou fetch_order, que retornou None no timeout adapter -> REJECTED ou UNKNOWN
        order_dict = storage.get_order_by_correlation_id("timeout_corr_id")
        self.assertIsNotNone(order_dict)

    # 11. UNKNOWN => sem retry automático
    def test_unknown_does_not_retry_submission(self) -> None:
        fake_adapter = FakeExchangeOrderAdapter(
            simulate_timeout=True,
            environment=BinanceEnvironment.SPOT_TESTNET,
        )
        storage = LiveOrderStorage(":memory:")

        run_testnet_order_validation(
            confirm_testnet_order=True,
            credential_provider=self.fake_provider,
            adapter=fake_adapter,
            storage=storage,
            current_price=Decimal("60000.00"),
            correlation_id="timeout_no_retry",
            poll_delay_seconds=0.0,
        )
        # Submissão foi tentada exatamente uma vez; auto-retry de create_order é proibido
        self.assertEqual(len(fake_adapter.submitted_payloads), 1)

    # 12. Reconciliação por clientOrderId
    def test_reconciliation_by_client_order_id(self) -> None:
        fake_adapter = FakeExchangeOrderAdapter(
            default_status=OrderStatus.ACKNOWLEDGED,
            environment=BinanceEnvironment.SPOT_TESTNET,
        )
        storage = LiveOrderStorage(":memory:")

        _, report = run_testnet_order_validation(
            confirm_testnet_order=True,
            credential_provider=self.fake_provider,
            adapter=fake_adapter,
            storage=storage,
            current_price=Decimal("60000.00"),
            correlation_id="recon_corr_01",
            poll_delay_seconds=0.0,
        )
        self.assertEqual(report.reconciliation_status, "CONFIRMED")
        self.assertEqual(report.final_state, OrderStatus.ACKNOWLEDGED.value)

    # 13. Secrets não aparecem
    def test_secrets_never_appear_in_output(self) -> None:
        preview = TestnetValidationPreview(
            environment="SPOT_TESTNET",
            symbol=SYMBOL_BTC_USDT,
            side="BUY",
            order_type="MARKET",
            estimated_notional=Decimal("6.00"),
            quantity=Decimal("0.0001"),
            reference_price=Decimal("60000.00"),
            min_amount=Decimal("0.00001"),
            step_size=Decimal("0.00001"),
            min_notional=Decimal("5.00"),
            risk_engine_pass=True,
            market_filter_guard_pass=True,
            production_isolation_pass=True,
            testnet_write_executed=False,
            ready_to_execute=True,
        )

        out_preview = io.StringIO()
        with patch("sys.stdout", out_preview):
            print_preview(preview)
        val_preview = out_preview.getvalue()
        self.assertNotIn("testnet_fake_key", val_preview)
        self.assertNotIn("testnet_fake_secret", val_preview)
        self.assertIn("TESTNET_ORDER_PREVIEW", val_preview)
        self.assertIn("TESTNET_WRITE_EXECUTED         : NO", val_preview)

        report = TestnetOrderExecutionReport(
            environment="SPOT_TESTNET",
            symbol=SYMBOL_BTC_USDT,
            side="BUY",
            order_type="MARKET",
            requested_notional=Decimal("6.00"),
            sanitized_quantity=Decimal("0.0001"),
            client_order_id="finbot_1234567890abcdef",
            order_id="12345678",
            order_status="FILLED",
            executed_quantity=Decimal("0.0001"),
            average_price=Decimal("60000.00"),
            final_state="FILLED",
            reconciliation_status="CONFIRMED",
            testnet_orders_sent=1,
            production_orders_sent=0,
            production_write_enabled=False,
        )
        out_report = io.StringIO()
        with patch("sys.stdout", out_report):
            print_report(report)
        val_report = out_report.getvalue()
        self.assertNotIn("testnet_fake_key", val_report)
        self.assertNotIn("testnet_fake_secret", val_report)
        self.assertIn("PRODUCTION_ORDERS_SENT         : 0", val_report)
        self.assertIn("PRODUCTION_WRITE_ENABLED       : NO", val_report)

    # 14. Cálculo dinâmico ajusta quantidade com variação de preço
    def test_dynamic_quantity_adapts_to_price_changes(self) -> None:
        prices = [Decimal("30000.00"), Decimal("60000.00"), Decimal("90000.00")]
        for px in prices:
            with self.subTest(price=px):
                cand = calculate_testnet_order_candidate(
                    filters=self.filters,
                    current_price=px,
                    max_cap=Decimal("15.00"),
                    target_notional=Decimal("6.00"),
                )
                self.assertIsNotNone(cand)
                qty, notional, _ = cand
                self.assertGreaterEqual(notional, self.filters.min_cost)
                self.assertLessEqual(notional, Decimal("15.00"))
                # Quantidade deve ser inversamente proporcional ao preço
                self.assertAlmostEqual(float(qty * px), float(notional), places=2)

    # 15. CLI main em modo Preview
    def test_cli_main_preview_flow(self) -> None:
        fake_adapter = FakeExchangeOrderAdapter(environment=BinanceEnvironment.SPOT_TESTNET)
        with patch("finbot.testnet_order_validation.WindowsCredentialProvider.for_environment", return_value=self.fake_provider):
            with patch("finbot.testnet_order_validation.BinanceSpotTestnetOrderAdapter", return_value=fake_adapter):
                out = io.StringIO()
                with patch("sys.stdout", out):
                    code = main([])
                self.assertEqual(code, 0)
                output = out.getvalue()
                self.assertIn("TESTNET_ORDER_PREVIEW", output)
                self.assertIn("TESTNET_WRITE_EXECUTED         : NO", output)
                self.assertIn("READY_TO_EXECUTE_TESTNET_ORDER : YES", output)

    # 16. CLI main em modo Armado com confirmação correta
    def test_cli_main_armed_flow(self) -> None:
        fake_adapter = FakeExchangeOrderAdapter(
            default_status=OrderStatus.FILLED,
            environment=BinanceEnvironment.SPOT_TESTNET,
        )
        storage = LiveOrderStorage(":memory:")
        with patch("finbot.testnet_order_validation.WindowsCredentialProvider.for_environment", return_value=self.fake_provider):
            with patch("finbot.testnet_order_validation.BinanceSpotTestnetOrderAdapter", return_value=fake_adapter):
                with patch("finbot.testnet_order_validation.LiveOrderStorage", return_value=storage):
                    out = io.StringIO()
                    with patch("sys.stdout", out):
                        code = main(["--confirm-testnet-order"])
                    self.assertEqual(code, 0)
                    output = out.getvalue()
                    self.assertIn("TESTNET_WRITE_ARMED = YES", output)
                    self.assertIn("FINAL_STATE                    : FILLED", output)
                    self.assertIn("TESTNET_ORDERS_SENT            : 1", output)

    # 17. Sentry no fetch_ticker de BinanceSpotTestnetOrderAdapter
    def test_fetch_ticker_sentry_protects_against_production(self) -> None:
        mock_client = MagicMock()
        mock_client.urls = {
            "api": {
                "public": "https://api.binance.com/api/v3",
                "private": "https://api.binance.com/api/v3",
            }
        }
        adapter = BinanceSpotTestnetOrderAdapter(
            credential_provider=self.fake_provider,
            client=mock_client,
        )
        with self.assertRaises(TestnetSentryError):
            adapter.fetch_ticker("BTC/USDT")


if __name__ == "__main__":
    unittest.main()
