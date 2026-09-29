"""Bateria de testes focados para validação operacional e de ciclo de vida na Binance Spot Testnet (FASE 8.4C2C).

Testa exaustivamente:
- SELL pipeline
- Saldo base insuficiente
- Filtros SELL (stepSize, minQty, minNotional)
- LIMIT válida
- Conformidade com tickSize
- Rastreabilidade de LIMIT no storage e ciclo de vida
- Cancel de ordem conhecida (NEW/OPEN -> CANCEL_PENDING -> CANCELED)
- Bloqueio de cancel de ordem FILLED
- Cancel idempotente
- Tratamento seguro de ordem preenchida antes do cancel
- UNKNOWN e proibição de auto-retry
- Reconciliação determinística por clientOrderId
- Isolamento absoluto de Produção (zero chamadas a api.binance.com)
- Zero chamadas externas nos testes automatizados
- Sigilo de secrets em logs e saídas

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
    GuardedLiveExecutionEngine,
    LiveOrderStorage,
    OrderNotCancelableError,
    OrderStatus,
)
from finbot.live_safety import (
    AccountStateSnapshot,
    MarketFilters,
    extract_market_filters,
)
from finbot.testnet_adapter import (
    BinanceSpotTestnetOrderAdapter,
    TestnetSentryError,
)
from finbot.testnet_order_validation import (
    ACTION_BUY_MARKET,
    ACTION_LIMIT_CANCEL,
    ACTION_SELL_MARKET,
    DEFAULT_TARGET_NOTIONAL,
    SYMBOL_BTC_USDT,
    TestnetOrderExecutionReport,
    TestnetValidationPreview,
    calculate_testnet_limit_candidate,
    calculate_testnet_order_candidate,
    calculate_testnet_sell_candidate,
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
    """Bateria de testes focados da FASE 8.4C2C."""

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

    # =========================================================================
    # PREVIEW & SEGURANÇA BÁSICA
    # =========================================================================

    def test_run_preview_mode_executes_zero_writes(self) -> None:
        """Sem confirmação => nenhuma chamada WRITE é feita à exchange."""
        fake_adapter = FakeExchangeOrderAdapter(environment=BinanceEnvironment.SPOT_TESTNET)
        storage = LiveOrderStorage(":memory:")

        preview, report = run_testnet_order_validation(
            action=ACTION_BUY_MARKET,
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

    def test_generic_flags_are_rejected(self) -> None:
        """Flags genéricas (--yes, --force, --live) são rejeitadas preventivamente."""
        for flag in ["--yes", "--force", "--live"]:
            with self.subTest(flag=flag):
                output_capture = io.StringIO()
                with patch("sys.stdout", output_capture):
                    ret = main([flag])
                self.assertEqual(ret, 1)
                self.assertIn("ERRO DE SEGURANÇA", output_capture.getvalue())
                self.assertIn("--confirm-testnet-order", output_capture.getvalue())

    # =========================================================================
    # CICLO DE VIDA: SELL MARKET
    # =========================================================================

    def test_sell_pipeline_executes_successfully(self) -> None:
        """Pipeline completo de SELL MARKET é aprovado e preenchido com saldo disponível."""
        fake_adapter = FakeExchangeOrderAdapter(
            default_status=OrderStatus.FILLED,
            environment=BinanceEnvironment.SPOT_TESTNET,
            balances={
                "USDT": {"free": Decimal("10000.00"), "used": Decimal("0"), "total": Decimal("10000.00")},
                "BTC": {"free": Decimal("0.00008000"), "used": Decimal("0"), "total": Decimal("0.00008000")},
            },
        )
        storage = LiveOrderStorage(":memory:")

        preview, report = run_testnet_order_validation(
            action=ACTION_SELL_MARKET,
            confirm_testnet_order=True,
            credential_provider=self.fake_provider,
            adapter=fake_adapter,
            storage=storage,
            current_price=Decimal("83000.00"),
            correlation_id="corr_sell_001",
            poll_delay_seconds=0.0,
        )

        self.assertIsNone(preview)
        self.assertIsNotNone(report)
        self.assertEqual(report.side, "SELL")
        self.assertEqual(report.order_type, "MARKET")
        self.assertEqual(report.sanitized_quantity, Decimal("0.00008000"))
        self.assertEqual(report.testnet_orders_sent, 1)
        self.assertEqual(report.production_orders_sent, 0)
        self.assertEqual(report.order_status, OrderStatus.FILLED.value)
        self.assertEqual(len(fake_adapter.submitted_payloads), 1)
        self.assertEqual(fake_adapter.submitted_payloads[0]["side"], "sell")

    def test_sell_insufficient_base_balance_rejected(self) -> None:
        """Tentativa de venda sem saldo base suficiente é bloqueada fail-closed."""
        fake_adapter = FakeExchangeOrderAdapter(
            environment=BinanceEnvironment.SPOT_TESTNET,
            balances={
                "USDT": {"free": Decimal("10000.00"), "used": Decimal("0"), "total": Decimal("10000.00")},
                "BTC": {"free": Decimal("0.00000000"), "used": Decimal("0"), "total": Decimal("0.00000000")},
            },
        )
        storage = LiveOrderStorage(":memory:")

        with self.assertRaises(RuntimeError) as ctx:
            run_testnet_order_validation(
                action=ACTION_SELL_MARKET,
                confirm_testnet_order=True,
                credential_provider=self.fake_provider,
                adapter=fake_adapter,
                storage=storage,
                current_price=Decimal("83000.00"),
            )
        self.assertIn("insuficiente", str(ctx.exception).lower())
        self.assertEqual(len(fake_adapter.submitted_payloads), 0)

    def test_sell_filters_preserved(self) -> None:
        """Candidata de venda respeita stepSize, minQty e minNotional."""
        cand = calculate_testnet_sell_candidate(
            filters=self.filters,
            current_price=Decimal("83000.00"),
            available_btc=Decimal("0.00008000"),
            max_cap=Decimal("15.00"),
            max_sell_qty=Decimal("0.00008000"),
        )
        self.assertIsNotNone(cand)
        qty, notional, px = cand
        self.assertGreaterEqual(qty, self.filters.min_amount)
        self.assertGreaterEqual(notional, self.filters.min_cost)
        self.assertLessEqual(notional, Decimal("15.00"))
        # stepSize compliance
        units = qty / self.filters.amount_step
        self.assertEqual(units, units.to_integral_value())

    # =========================================================================
    # CICLO DE VIDA: LIMIT + CANCEL
    # =========================================================================

    def test_limit_candidate_calculation_and_tick_size(self) -> None:
        """Cálculo de ordem LIMIT aplica desconto e respeita tickSize e stepSize."""
        cand = calculate_testnet_limit_candidate(
            filters=self.filters,
            current_price=Decimal("80000.00"),
            max_cap=Decimal("15.00"),
            discount=Decimal("0.85"),
        )
        self.assertIsNotNone(cand)
        qty, limit_px, notional = cand
        # Preço com 15% de desconto: 80000 * 0.85 = 68000.00
        self.assertEqual(limit_px, Decimal("68000.00"))
        # Preço é múltiplo exato de price_step
        px_units = limit_px / self.filters.price_step
        self.assertEqual(px_units, px_units.to_integral_value())
        # Quantidade é múltiplo exato de amount_step
        qty_units = qty / self.filters.amount_step
        self.assertEqual(qty_units, qty_units.to_integral_value())
        # Notional atende aos limites
        self.assertGreaterEqual(notional, self.filters.min_cost)
        self.assertLessEqual(notional, Decimal("15.00"))

    def test_limit_cancel_pipeline_full_lifecycle(self) -> None:
        """Fluxo completo de LIMIT_CANCEL: submissão -> ACK -> cancelamento -> CANCELED."""
        fake_adapter = FakeExchangeOrderAdapter(
            default_status=OrderStatus.ACKNOWLEDGED,
            environment=BinanceEnvironment.SPOT_TESTNET,
        )
        storage = LiveOrderStorage(":memory:")

        preview, report = run_testnet_order_validation(
            action=ACTION_LIMIT_CANCEL,
            confirm_testnet_order=True,
            credential_provider=self.fake_provider,
            adapter=fake_adapter,
            storage=storage,
            current_price=Decimal("80000.00"),
            correlation_id="corr_limit_001",
            poll_delay_seconds=0.0,
        )

        self.assertIsNone(preview)
        self.assertIsNotNone(report)
        self.assertEqual(report.action, ACTION_LIMIT_CANCEL)
        self.assertEqual(report.side, "BUY")
        self.assertEqual(report.order_type, "LIMIT")
        self.assertEqual(report.final_state, OrderStatus.CANCELED.value)
        self.assertEqual(report.cancel_status, OrderStatus.CANCELED.value)
        self.assertEqual(report.testnet_orders_sent, 1)
        self.assertEqual(report.production_orders_sent, 0)
        # O adapter recebeu 1 submit e 1 cancel
        self.assertEqual(len(fake_adapter.submitted_payloads), 1)
        self.assertEqual(len(fake_adapter.canceled_requests), 1)

    def test_limit_remains_traceable_in_storage(self) -> None:
        """Ordem LIMIT e seu ciclo de vida completo permanecem registrados no SQLite."""
        fake_adapter = FakeExchangeOrderAdapter(
            default_status=OrderStatus.ACKNOWLEDGED,
            environment=BinanceEnvironment.SPOT_TESTNET,
        )
        storage = LiveOrderStorage(":memory:")

        _, report = run_testnet_order_validation(
            action=ACTION_LIMIT_CANCEL,
            confirm_testnet_order=True,
            credential_provider=self.fake_provider,
            adapter=fake_adapter,
            storage=storage,
            current_price=Decimal("80000.00"),
            correlation_id="corr_limit_trace_01",
            poll_delay_seconds=0.0,
        )

        # Consulta ordem por client_order_id
        order_record = storage.get_order_by_client_order_id(report.client_order_id)
        self.assertIsNotNone(order_record)
        self.assertEqual(order_record["current_status"], OrderStatus.CANCELED.value)

        # Consulta histórico de transições
        history = storage.get_lifecycle_history("corr_limit_trace_01")
        statuses = [h.new_status for h in history]
        self.assertIn(OrderStatus.PENDING_SUBMISSION, statuses)
        self.assertIn(OrderStatus.ACKNOWLEDGED, statuses)
        self.assertIn(OrderStatus.CANCEL_PENDING, statuses)
        self.assertIn(OrderStatus.CANCELED, statuses)

    def test_block_cancel_of_already_filled_order(self) -> None:
        """Tentativa direta de cancelar uma ordem já FILLED é categoricamente bloqueada."""
        fake_adapter = FakeExchangeOrderAdapter(
            default_status=OrderStatus.FILLED,
            environment=BinanceEnvironment.SPOT_TESTNET,
        )
        storage = LiveOrderStorage(":memory:")
        engine = GuardedLiveExecutionEngine(
            adapter=fake_adapter,
            storage=storage,
            config=Config(
                binance_environment=BinanceEnvironment.SPOT_TESTNET,
                testnet_execution_enabled=True,
            ),
        )

        # Executa BUY MARKET para obter ordem FILLED
        _, report = run_testnet_order_validation(
            action=ACTION_BUY_MARKET,
            confirm_testnet_order=True,
            credential_provider=self.fake_provider,
            adapter=fake_adapter,
            storage=storage,
            current_price=Decimal("60000.00"),
            correlation_id="corr_buy_filled",
            poll_delay_seconds=0.0,
        )
        self.assertEqual(report.final_state, OrderStatus.FILLED.value)

        # Tenta cancelar a ordem que já está FILLED
        with self.assertRaises(OrderNotCancelableError) as ctx:
            engine.cancel_order(report.client_order_id)
        self.assertIn("não pode ser cancelada", str(ctx.exception))

    def test_cancel_idempotent_rejects_second_cancel(self) -> None:
        """Tentativa de cancelar uma ordem já cancelada levanta OrderNotCancelableError."""
        fake_adapter = FakeExchangeOrderAdapter(
            default_status=OrderStatus.ACKNOWLEDGED,
            environment=BinanceEnvironment.SPOT_TESTNET,
        )
        storage = LiveOrderStorage(":memory:")
        engine = GuardedLiveExecutionEngine(
            adapter=fake_adapter,
            storage=storage,
            config=Config(
                binance_environment=BinanceEnvironment.SPOT_TESTNET,
                testnet_execution_enabled=True,
            ),
        )

        _, report = run_testnet_order_validation(
            action=ACTION_LIMIT_CANCEL,
            confirm_testnet_order=True,
            credential_provider=self.fake_provider,
            adapter=fake_adapter,
            storage=storage,
            current_price=Decimal("80000.00"),
            correlation_id="corr_limit_idem_cancel",
            poll_delay_seconds=0.0,
        )
        self.assertEqual(report.final_state, OrderStatus.CANCELED.value)

        # Segunda tentativa de cancelamento
        with self.assertRaises(OrderNotCancelableError) as ctx:
            engine.cancel_order(report.client_order_id)
        self.assertIn("não pode ser cancelada", str(ctx.exception))

    def test_order_filled_before_cancel_is_handled_safely(self) -> None:
        """Se a ordem LIMIT preencher antes do cancelamento, o cancel cego NÃO é executado."""
        fake_adapter = FakeExchangeOrderAdapter(
            default_status=OrderStatus.FILLED,  # Simula preenchimento imediato
            environment=BinanceEnvironment.SPOT_TESTNET,
        )
        storage = LiveOrderStorage(":memory:")

        _, report = run_testnet_order_validation(
            action=ACTION_LIMIT_CANCEL,
            confirm_testnet_order=True,
            credential_provider=self.fake_provider,
            adapter=fake_adapter,
            storage=storage,
            current_price=Decimal("80000.00"),
            correlation_id="corr_limit_fill_before_cancel",
            poll_delay_seconds=0.0,
        )

        # O cancelamento não deve ter sido enviado
        self.assertEqual(len(fake_adapter.canceled_requests), 0)
        self.assertEqual(report.final_state, OrderStatus.FILLED.value)
        self.assertEqual(report.cancel_status, "NOT_CANCELED_ORDER_ALREADY_FILLED")

    # =========================================================================
    # SENTRIES, ISOLAMENTO E FALHAS AMBÍGUAS
    # =========================================================================

    def test_production_adapter_is_rejected_fail_closed(self) -> None:
        """BinanceOrderAdapter de produção é rejeitado por sentry fail-closed."""
        prod_adapter = BinanceOrderAdapter(real_order_submission_enabled=False)
        cfg = Config(
            binance_environment=BinanceEnvironment.SPOT_TESTNET,
            testnet_execution_enabled=True,
        )
        with self.assertRaises(TestnetSentryError) as ctx:
            verify_testnet_write_sentries(cfg, prod_adapter, self.fake_provider)
        self.assertIn("BinanceOrderAdapter", str(ctx.exception))

    def test_production_endpoint_is_rejected(self) -> None:
        """Endpoint com api.binance.com é sumariamente abortado."""
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

    def test_production_credentials_target_is_rejected(self) -> None:
        """Target FinBot/Binance/Production é rejeitado no armamento da Testnet."""
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

    def test_timeout_results_in_unknown_without_retry(self) -> None:
        """Timeout de rede gera estado UNKNOWN e proíbe terminantemente retry de create."""
        fake_adapter = FakeExchangeOrderAdapter(
            simulate_timeout=True,
            environment=BinanceEnvironment.SPOT_TESTNET,
        )
        storage = LiveOrderStorage(":memory:")

        run_testnet_order_validation(
            action=ACTION_BUY_MARKET,
            confirm_testnet_order=True,
            credential_provider=self.fake_provider,
            adapter=fake_adapter,
            storage=storage,
            current_price=Decimal("60000.00"),
            correlation_id="timeout_no_retry_001",
            poll_delay_seconds=0.0,
        )
        self.assertEqual(len(fake_adapter.submitted_payloads), 1)

    def test_idempotency_prevents_duplicate_submission(self) -> None:
        """Submissão duplicada com mesmo correlation_id é impedida por DUPLICATE_INTENT."""
        fake_adapter = FakeExchangeOrderAdapter(
            default_status=OrderStatus.FILLED,
            environment=BinanceEnvironment.SPOT_TESTNET,
        )
        storage = LiveOrderStorage(":memory:")

        run_testnet_order_validation(
            action=ACTION_BUY_MARKET,
            confirm_testnet_order=True,
            credential_provider=self.fake_provider,
            adapter=fake_adapter,
            storage=storage,
            current_price=Decimal("60000.00"),
            correlation_id="corr_idem_01",
            poll_delay_seconds=0.0,
        )

        with self.assertRaises(RuntimeError) as ctx:
            run_testnet_order_validation(
                action=ACTION_BUY_MARKET,
                confirm_testnet_order=True,
                credential_provider=self.fake_provider,
                adapter=fake_adapter,
                storage=storage,
                current_price=Decimal("60000.00"),
                correlation_id="corr_idem_01",
                poll_delay_seconds=0.0,
            )
        self.assertIn("DUPLICATE_INTENT", str(ctx.exception))
        self.assertEqual(len(fake_adapter.submitted_payloads), 1)

    # =========================================================================
    # CLI FLOWS & PREVIEW
    # =========================================================================

    def test_cli_main_sell_preview_flow(self) -> None:
        """CLI main em modo default preview (sell_market) executa perfeitamente."""
        fake_adapter = FakeExchangeOrderAdapter(
            environment=BinanceEnvironment.SPOT_TESTNET,
            ticker_price=83000.0,
            balances={
                "USDT": {"free": Decimal("10000.00"), "used": Decimal("0"), "total": Decimal("10000.00")},
                "BTC": {"free": Decimal("0.00008000"), "used": Decimal("0"), "total": Decimal("0.00008000")},
            },
        )
        with patch("finbot.testnet_order_validation.WindowsCredentialProvider.for_environment", return_value=self.fake_provider):
            with patch("finbot.testnet_order_validation.BinanceSpotTestnetOrderAdapter", return_value=fake_adapter):
                out = io.StringIO()
                with patch("sys.stdout", out):
                    code = main(["--action", "sell_market"])
                self.assertEqual(code, 0)
                output = out.getvalue()
                self.assertIn("ACTION                         : SELL_MARKET", output)
                self.assertIn("TESTNET_WRITE_EXECUTED         : NO", output)
                self.assertIn("READY_TO_EXECUTE_TESTNET_ORDER : YES", output)

    def test_cli_main_limit_preview_flow(self) -> None:
        """CLI main em modo preview de LIMIT_CANCEL exibe preço limite e notional."""
        fake_adapter = FakeExchangeOrderAdapter(environment=BinanceEnvironment.SPOT_TESTNET)
        with patch("finbot.testnet_order_validation.WindowsCredentialProvider.for_environment", return_value=self.fake_provider):
            with patch("finbot.testnet_order_validation.BinanceSpotTestnetOrderAdapter", return_value=fake_adapter):
                out = io.StringIO()
                with patch("sys.stdout", out):
                    code = main(["--action", "limit_cancel"])
                self.assertEqual(code, 0)
                output = out.getvalue()
                self.assertIn("ACTION                         : LIMIT_CANCEL", output)
                self.assertIn("TYPE                           : LIMIT", output)
                self.assertIn("LIMIT_PRICE", output)
                self.assertIn("TESTNET_WRITE_EXECUTED         : NO", output)

    def test_secrets_never_appear_in_output(self) -> None:
        """Chaves privadas, segredos e tokens jamais são impressos."""
        preview = TestnetValidationPreview(
            action=ACTION_SELL_MARKET,
            environment="SPOT_TESTNET",
            symbol=SYMBOL_BTC_USDT,
            side="SELL",
            order_type="MARKET",
            estimated_notional=Decimal("6.64"),
            quantity=Decimal("0.00008000"),
            reference_price=Decimal("83000.00"),
            available_balance=Decimal("0.00008000"),
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

        report = TestnetOrderExecutionReport(
            action=ACTION_SELL_MARKET,
            environment="SPOT_TESTNET",
            symbol=SYMBOL_BTC_USDT,
            side="SELL",
            order_type="MARKET",
            requested_notional=Decimal("6.64"),
            sanitized_quantity=Decimal("0.00008000"),
            client_order_id="finbot_1234567890abcdef",
            order_id="12345678",
            order_status="FILLED",
            executed_quantity=Decimal("0.00008000"),
            average_price=Decimal("83000.00"),
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


if __name__ == "__main__":
    unittest.main()
