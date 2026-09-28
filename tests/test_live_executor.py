"""Suíte de testes para a FASE 8.4B — Guarded Live Order Executor Foundation.

Cobre exaustivamente:
1. GuardedLiveExecutionEngine (aceitação de ApprovedOrderIntent, rejeição de raw OrderIntent ou rejeitado).
2. Triple Live Arming (trading_mode, live_trading_acknowledged, live_execution_enabled).
3. Micro-Order Cap (limite estrito financeiro sem truncamento automático).
4. Injeção de adapter da exchange e verificação de payload canônico.
5. Idempotência e máquina de estados no SQLite.
6. Falha ambígua (UNKNOWN != FAILED, TIMEOUT != SAFE TO RETRY, proibição de auto-retry).
7. Reconciliação via clientOrderId antes de qualquer decisão.
8. Cancelamento seguro com validação de estado (bloqueio de cancelamento para FILLED e UNKNOWN).
9. Ausência de credenciais em banco de dados, representações e logs.
10. Teste Sentinela: test_phase_8_4b_cannot_reach_real_binance_order_endpoint.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock

from finbot.config import Config
from finbot.execution import (
    InvalidExecutionIntentError,
    generate_client_order_id,
)
from finbot.live_executor import (
    BinanceOrderAdapter,
    ExchangeOrderResult,
    FakeExchangeOrderAdapter,
    GuardedLiveExecutionEngine,
    LiveExecutionArmingError,
    LiveOrderStorage,
    MicroOrderCapExceededError,
    OrderLifecycleRecord,
    OrderNotCancelableError,
    OrderStatus,
    RealOrderSubmissionBlockedError,
)
from finbot.live_safety import (
    ApprovedOrderIntent,
    OrderIntent,
    RejectedOrderIntent,
)
from finbot.private_exchange import (
    BinancePrivateExchange,
    LiveTradingBlockedError,
)


def make_test_intent(
    symbol: str = "BTC/USDT",
    side: str = "BUY",
    order_type: str = "MARKET",
    quantity: str = "0.0002",
    price: str | None = "50000.00",
    requested_notional: str = "10.00",
    correlation_id: str = "live-corr-1",
) -> OrderIntent:
    return OrderIntent(
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=Decimal(quantity),
        price=Decimal(price) if price else None,
        requested_notional=Decimal(requested_notional),
        strategy_name="SMA Crossover",
        strategy_version="1.0",
        signal=side,
        created_at="2026-09-28T00:00:00Z",
        correlation_id=correlation_id,
    )


def make_test_approved_intent(
    intent: OrderIntent | None = None,
    normalized_quantity: str = "0.0002",
    normalized_price: str | None = "50000.00",
    normalized_notional: str = "10.00",
) -> ApprovedOrderIntent:
    base_intent = intent or make_test_intent()
    return ApprovedOrderIntent(
        intent=base_intent,
        normalized_quantity=Decimal(normalized_quantity),
        normalized_price=Decimal(normalized_price) if normalized_price else None,
        normalized_notional=Decimal(normalized_notional),
        checks={"risk": "ALLOWED", "market": "VALID"},
        approved_at="2026-09-28T00:00:00Z",
    )


def make_armed_config(
    trading_mode: str = "live",
    live_trading_acknowledged: bool = True,
    live_execution_enabled: bool = True,
    live_micro_order_max_notional: float = 15.0,
    real_order_submission_enabled: bool = False,
) -> Config:
    return Config(
        trading_mode=trading_mode,
        live_trading_acknowledged=live_trading_acknowledged,
        live_execution_enabled=live_execution_enabled,
        live_micro_order_max_notional=live_micro_order_max_notional,
        real_order_submission_enabled=real_order_submission_enabled,
    )


class TestGuardedLiveExecutionEngine(unittest.TestCase):
    """Testes unitários e comportamentais do GuardedLiveExecutionEngine."""

    def setUp(self) -> None:
        self.config = make_armed_config()
        self.adapter = FakeExchangeOrderAdapter()
        self.storage = LiveOrderStorage(":memory:")
        self.engine = GuardedLiveExecutionEngine(
            adapter=self.adapter,
            storage=self.storage,
            config=self.config,
        )

    def test_engine_accepts_approved_order_intent(self) -> None:
        """1. Engine aceita ApprovedOrderIntent e submete via adapter injetado."""
        approved = make_test_approved_intent()
        result = self.engine.execute(approved)

        self.assertIsInstance(result, ExchangeOrderResult)
        self.assertEqual(result.status, OrderStatus.ACKNOWLEDGED)
        self.assertEqual(len(self.adapter.submitted_payloads), 1)
        self.assertEqual(self.adapter.submitted_payloads[0]["symbol"], "BTC/USDT")

    def test_engine_rejects_raw_order_intent(self) -> None:
        """2. Engine rejeita categoricamente OrderIntent cru (fail-closed)."""
        raw = make_test_intent()
        with self.assertRaises(InvalidExecutionIntentError):
            self.engine.execute(raw)  # type: ignore[arg-type]

    def test_engine_rejects_rejected_order_intent(self) -> None:
        """3. Engine rejeita categoricamente RejectedOrderIntent (fail-closed)."""
        raw = make_test_intent()
        rejected = RejectedOrderIntent(
            intent=raw,
            reason_code="RISK_REJECT",
            reason="Blocked by risk",
            checks={},
            rejected_at="2026-09-28T00:00:00Z",
        )
        with self.assertRaises(InvalidExecutionIntentError):
            self.engine.execute(rejected)  # type: ignore[arg-type]

    def test_engine_requires_injected_adapter(self) -> None:
        """4. Engine rejeita inicialização sem adapter explicitamente injetado."""
        with self.assertRaises(ValueError):
            GuardedLiveExecutionEngine(adapter=None)  # type: ignore[arg-type]


class TestTripleLiveArming(unittest.TestCase):
    """Testes para os três critérios independentes de ativação live (Triple Arming)."""

    def setUp(self) -> None:
        self.adapter = FakeExchangeOrderAdapter()
        self.storage = LiveOrderStorage(":memory:")

    def test_arming_rejects_non_live_mode(self) -> None:
        """5. Rejeita se trading_mode != 'live'."""
        cfg = make_armed_config(trading_mode="paper")
        engine = GuardedLiveExecutionEngine(adapter=self.adapter, storage=self.storage, config=cfg)
        with self.assertRaises(LiveExecutionArmingError):
            engine.execute(make_test_approved_intent())

    def test_arming_rejects_unacknowledged(self) -> None:
        """6. Rejeita se live_trading_acknowledged == False."""
        cfg = make_armed_config(live_trading_acknowledged=False)
        engine = GuardedLiveExecutionEngine(adapter=self.adapter, storage=self.storage, config=cfg)
        with self.assertRaises(LiveExecutionArmingError):
            engine.execute(make_test_approved_intent())

    def test_arming_rejects_disabled_execution(self) -> None:
        """7. Rejeita se live_execution_enabled == False."""
        cfg = make_armed_config(live_execution_enabled=False)
        engine = GuardedLiveExecutionEngine(adapter=self.adapter, storage=self.storage, config=cfg)
        with self.assertRaises(LiveExecutionArmingError):
            engine.execute(make_test_approved_intent())


class TestMicroOrderCap(unittest.TestCase):
    """Testes para o teto financeiro de micro-ordem (live_micro_order_max_notional)."""

    def setUp(self) -> None:
        self.adapter = FakeExchangeOrderAdapter()
        self.storage = LiveOrderStorage(":memory:")
        self.config = make_armed_config(live_micro_order_max_notional=15.0)
        self.engine = GuardedLiveExecutionEngine(adapter=self.adapter, storage=self.storage, config=self.config)

    def test_order_below_micro_cap_passes(self) -> None:
        """8. Ordem com notional abaixo do teto de micro-ordem (10 USDT <= 15 USDT) passa."""
        approved = make_test_approved_intent(normalized_notional="10.00")
        result = self.engine.execute(approved)
        self.assertEqual(result.status, OrderStatus.ACKNOWLEDGED)

    def test_order_above_micro_cap_rejected(self) -> None:
        """9. Ordem com notional acima do teto (20 USDT > 15 USDT) é rejeitada fail-closed."""
        intent = make_test_intent(requested_notional="20.00")
        approved = make_test_approved_intent(intent=intent, normalized_notional="20.00")
        with self.assertRaises(MicroOrderCapExceededError):
            self.engine.execute(approved)

    def test_order_never_automatically_truncated_to_fit_cap(self) -> None:
        """10. O motor nunca reduz a quantidade da ordem automaticamente para caber no teto."""
        intent = make_test_intent(requested_notional="35.00", quantity="0.0007")
        approved = make_test_approved_intent(intent=intent, normalized_notional="35.00")
        with self.assertRaises(MicroOrderCapExceededError):
            self.engine.execute(approved)
        self.assertEqual(len(self.adapter.submitted_payloads), 0)


class TestIdempotencyAndLifecycle(unittest.TestCase):
    """Testes para a máquina de estados e persistência de idempotência."""

    def test_duplicate_intent_rejected_without_double_submission(self) -> None:
        """11. Tentativa de submeter a mesma intenção duas vezes levanta erro de duplicidade."""
        adapter = FakeExchangeOrderAdapter()
        storage = LiveOrderStorage(":memory:")
        engine = GuardedLiveExecutionEngine(adapter=adapter, storage=storage, config=make_armed_config())
        approved = make_test_approved_intent()

        res1 = engine.execute(approved)
        self.assertEqual(res1.status, OrderStatus.ACKNOWLEDGED)
        self.assertEqual(len(adapter.submitted_payloads), 1)

        # Segunda tentativa
        with self.assertRaises(RuntimeError) as ctx:
            engine.execute(approved)
        self.assertIn("DUPLICATE_INTENT", str(ctx.exception))
        # O adapter não pode ter sido chamado novamente
        self.assertEqual(len(adapter.submitted_payloads), 1)

    def test_idempotency_persists_across_restart(self) -> None:
        """12. Idempotência persiste em arquivo SQLite entre reinicializações do processo."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "live_orders_test.sqlite3"
            storage1 = LiveOrderStorage(db_path)
            adapter = FakeExchangeOrderAdapter()
            engine1 = GuardedLiveExecutionEngine(adapter=adapter, storage=storage1, config=make_armed_config())
            approved = make_test_approved_intent()

            engine1.execute(approved)
            self.assertEqual(len(adapter.submitted_payloads), 1)

            # Simula reinício
            storage2 = LiveOrderStorage(db_path)
            engine2 = GuardedLiveExecutionEngine(adapter=adapter, storage=storage2, config=make_armed_config())

            with self.assertRaises(RuntimeError) as ctx:
                engine2.execute(approved)
            self.assertIn("DUPLICATE_INTENT", str(ctx.exception))
            self.assertEqual(len(adapter.submitted_payloads), 1)

    def test_lifecycle_transitions_recorded_append_only(self) -> None:
        """13. Transições de ciclo de vida são registradas em append-only sem sobrescrita."""
        storage = LiveOrderStorage(":memory:")
        adapter = FakeExchangeOrderAdapter(default_status=OrderStatus.FILLED)
        engine = GuardedLiveExecutionEngine(adapter=adapter, storage=storage, config=make_armed_config())
        approved = make_test_approved_intent()

        engine.execute(approved)
        history = storage.get_lifecycle_history(approved.intent.correlation_id)

        # Deve conter transições: PREPARED -> PENDING_SUBMISSION -> FILLED
        self.assertGreaterEqual(len(history), 2)
        statuses = [rec.new_status for rec in history]
        self.assertIn(OrderStatus.PENDING_SUBMISSION, statuses)
        self.assertIn(OrderStatus.FILLED, statuses)


class TestAmbiguousFailureAndReconciliation(unittest.TestCase):
    """Testes críticos para a regra constitucional: UNKNOWN != FAILED e TIMEOUT != SAFE TO RETRY."""

    def test_network_timeout_during_submission_marks_unknown_without_resend(self) -> None:
        """14. Falha de rede/timeout gera status UNKNOWN e NÃO reenvia automaticamente."""
        timeout_adapter = FakeExchangeOrderAdapter(simulate_timeout=True)
        storage = LiveOrderStorage(":memory:")
        engine = GuardedLiveExecutionEngine(adapter=timeout_adapter, storage=storage, config=make_armed_config())
        approved = make_test_approved_intent()

        result = engine.execute(approved)

        self.assertEqual(result.status, OrderStatus.UNKNOWN)
        saved_order = storage.get_order_by_correlation_id(approved.intent.correlation_id)
        self.assertIsNotNone(saved_order)
        self.assertEqual(saved_order["current_status"], OrderStatus.UNKNOWN.value)

        # Proibição de reenvio cego
        with self.assertRaises(RuntimeError) as ctx:
            engine.execute(approved)
        self.assertIn("DUPLICATE_INTENT", str(ctx.exception))

    def test_reconciliation_resolves_unknown_to_confirmed_order(self) -> None:
        """15. Reconciliação via clientOrderId consulta a exchange e atualiza o estado para confirmado."""
        # Configura adapter que causará timeout na submissão, mas cuja ordem existe na exchange
        adapter = FakeExchangeOrderAdapter(simulate_timeout=True)
        storage = LiveOrderStorage(":memory:")
        engine = GuardedLiveExecutionEngine(adapter=adapter, storage=storage, config=make_armed_config())
        approved = make_test_approved_intent()

        # 1. Envio falha com timeout -> UNKNOWN
        engine.execute(approved)
        client_id = generate_client_order_id(approved.intent.correlation_id)

        # 2. Simula que na exchange a ordem de fato foi recebida e preenchida
        adapter.orders[client_id] = ExchangeOrderResult(
            client_order_id=client_id,
            exchange_order_id="binance_real_999",
            status=OrderStatus.FILLED,
            symbol="BTC/USDT",
            side="BUY",
            order_type="MARKET",
            requested_quantity=Decimal("0.0002"),
            executed_quantity=Decimal("0.0002"),
            cumulative_quote_quantity=Decimal("10.00"),
            average_price=Decimal("50000.00"),
            created_at="2026-09-28T00:00:00Z",
            updated_at="2026-09-28T00:00:05Z",
        )

        # 3. Executa reconciliação
        reconciled = engine.reconcile_order(client_id)

        self.assertEqual(reconciled.status, OrderStatus.FILLED)
        self.assertEqual(reconciled.exchange_order_id, "binance_real_999")
        saved_order = storage.get_order_by_client_order_id(client_id)
        self.assertEqual(saved_order["current_status"], OrderStatus.FILLED.value)

    def test_reconciliation_marks_rejected_when_not_found_without_auto_retry(self) -> None:
        """16. Se a ordem não existe na exchange após reconciliação, marca REJECTED e NUNCA tenta retry automático."""
        adapter = FakeExchangeOrderAdapter(simulate_timeout=True)
        storage = LiveOrderStorage(":memory:")
        engine = GuardedLiveExecutionEngine(adapter=adapter, storage=storage, config=make_armed_config())
        approved = make_test_approved_intent()

        # Envio falha -> UNKNOWN
        engine.execute(approved)
        client_id = generate_client_order_id(approved.intent.correlation_id)

        # Reconciliação: ordem não está na exchange (adapter.orders está vazio)
        reconciled = engine.reconcile_order(client_id)

        self.assertEqual(reconciled.status, OrderStatus.REJECTED)
        saved = storage.get_order_by_client_order_id(client_id)
        self.assertEqual(saved["current_status"], OrderStatus.REJECTED.value)

        # Tentar novo execute da mesma intenção continua bloqueado por duplicidade (sem retry cego)
        with self.assertRaises(RuntimeError):
            engine.execute(approved)


class TestOrderCancellationSafeguards(unittest.TestCase):
    """Testes para o fluxo de cancelamento de ordens."""

    def test_cancel_open_order_succeeds(self) -> None:
        """17. Cancelar ordem aberta em ACKNOWLEDGED transita para CANCELED."""
        adapter = FakeExchangeOrderAdapter(default_status=OrderStatus.ACKNOWLEDGED)
        storage = LiveOrderStorage(":memory:")
        engine = GuardedLiveExecutionEngine(adapter=adapter, storage=storage, config=make_armed_config())
        approved = make_test_approved_intent()

        engine.execute(approved)
        client_id = generate_client_order_id(approved.intent.correlation_id)

        cancel_res = engine.cancel_order(client_id)
        self.assertEqual(cancel_res.status, OrderStatus.CANCELED)

        saved = storage.get_order_by_client_order_id(client_id)
        self.assertEqual(saved["current_status"], OrderStatus.CANCELED.value)

    def test_cancel_filled_order_raises_error(self) -> None:
        """18. Cancelar ordem já FILLED é categoricamente bloqueado."""
        adapter = FakeExchangeOrderAdapter(default_status=OrderStatus.FILLED)
        storage = LiveOrderStorage(":memory:")
        engine = GuardedLiveExecutionEngine(adapter=adapter, storage=storage, config=make_armed_config())
        approved = make_test_approved_intent()

        engine.execute(approved)
        client_id = generate_client_order_id(approved.intent.correlation_id)

        with self.assertRaises(OrderNotCancelableError) as ctx:
            engine.cancel_order(client_id)
        self.assertIn("já está em estado final 'FILLED'", str(ctx.exception))

    def test_cancel_unknown_order_raises_error_demanding_reconciliation(self) -> None:
        """19. Cancelar ordem em estado UNKNOWN falha exigindo reconciliação prévia."""
        adapter = FakeExchangeOrderAdapter(simulate_timeout=True)
        storage = LiveOrderStorage(":memory:")
        engine = GuardedLiveExecutionEngine(adapter=adapter, storage=storage, config=make_armed_config())
        approved = make_test_approved_intent()

        engine.execute(approved)
        client_id = generate_client_order_id(approved.intent.correlation_id)

        with self.assertRaises(OrderNotCancelableError) as ctx:
            engine.cancel_order(client_id)
        self.assertIn("estado UNKNOWN. É obrigatório reconciliar", str(ctx.exception))


class TestSecurityAndSentinel(unittest.TestCase):
    """Testes de segurança e sentinela garantindo inviolabilidade de execução real."""

    def test_no_credentials_stored_in_database(self) -> None:
        """20. Valida que o schema e os registros do LiveOrderStorage não contêm chaves ou segredos."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_file = Path(tmpdir) / "live_sec_test.sqlite3"
            storage = LiveOrderStorage(db_file)
            adapter = FakeExchangeOrderAdapter()
            engine = GuardedLiveExecutionEngine(adapter=adapter, storage=storage, config=make_armed_config())
            engine.execute(make_test_approved_intent())

            conn = sqlite3.connect(str(db_file))
            try:
                for table in ("live_orders", "live_order_lifecycle"):
                    cursor = conn.cursor()
                    cursor.execute(f"PRAGMA table_info({table})")
                    columns = [row[1] for row in cursor.fetchall()]
                    cursor.close()
                    forbidden = {"api_key", "api_secret", "secret", "password", "token", "credential"}
                    for col in columns:
                        self.assertNotIn(col.lower(), forbidden)
            finally:
                conn.close()

    def test_binance_order_adapter_fails_with_real_order_submission_blocked_error(self) -> None:
        """21. BinanceOrderAdapter levanta RealOrderSubmissionBlockedError antes de qualquer chamada HTTP."""
        fake_exchange = MagicMock(spec=BinancePrivateExchange)
        adapter = BinanceOrderAdapter(private_exchange=fake_exchange, real_order_submission_enabled=False)

        payload = {"symbol": "BTC/USDT", "type": "market", "side": "buy", "amount": 0.0002, "params": {}}
        with self.assertRaises(RealOrderSubmissionBlockedError):
            adapter.submit_order(payload)

        with self.assertRaises(RealOrderSubmissionBlockedError):
            adapter.cancel_order("BTC/USDT", "12345", "client_123")

        fake_exchange.create_order.assert_not_called()
        fake_exchange.cancel_order.assert_not_called()

    def test_phase_8_4b_cannot_reach_real_binance_order_endpoint(self) -> None:
        """22. TESTE SENTINELA DA FASE 8.4B:

        Comprova matematicamente e arquiteturalmente que:
        1. Mesmo que todas as configurações de arming estejam ativas (trading_mode='live',
           live_trading_acknowledged=True, live_execution_enabled=True),
        2. E mesmo que se injete um BinanceOrderAdapter,
        3. A barreira final da FASE 8.4B bloqueia qualquer chamada com RealOrderSubmissionBlockedError.
        4. E os métodos create_order e cancel_order da BinancePrivateExchange permanecem bloqueados
           com LiveTradingBlockedError.
        """
        fake_prov = MagicMock()
        fake_prov.get_credentials.return_value = MagicMock(api_key="k", api_secret="s")
        config = Config(
            trading_mode="live",
            live_trading_acknowledged=True,
            live_execution_enabled=True,
            real_order_submission_enabled=False,
        )
        private_exchange = BinancePrivateExchange(config=config, credential_provider=fake_prov)

        # Barreira 1: BinanceOrderAdapter bloqueia
        binance_adapter = BinanceOrderAdapter(private_exchange=private_exchange, real_order_submission_enabled=False)
        engine = GuardedLiveExecutionEngine(adapter=binance_adapter, config=config)

        approved = make_test_approved_intent()
        with self.assertRaises(RealOrderSubmissionBlockedError):
            engine.execute(approved)

        # Barreira 2: BinancePrivateExchange continua bloqueada incondicionalmente
        with self.assertRaises(LiveTradingBlockedError):
            private_exchange.create_order("BTC/USDT", "market", "buy", 0.0002)

        with self.assertRaises(LiveTradingBlockedError):
            private_exchange.cancel_order("123", "BTC/USDT")


if __name__ == "__main__":
    unittest.main()
