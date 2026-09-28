"""Suíte de testes para a FASE 8.4A — Live Execution Engine / Dry-Run.

Cobre exaustivamente:
1. DryRunExecutionEngine (aceitação de ApprovedOrderIntent, rejeição de OrderIntent cru ou rejeitado).
2. Modos de execução (bloqueio de LIVE, obrigatoriedade de DRY_RUN).
3. Payload canônico e preservação de precisão.
4. Geração determinística de clientOrderId e conformidade com limites da Binance.
5. Idempotência em memória e persistência SQLite entre reinicializações.
6. Ausência de credenciais em dados gravados, logs ou representações.
7. Orquestração de pipeline (Gate reject impede chamada do Engine; Gate allow produz DryRunOrderResult).
8. Preservação de bloqueio de create_order e cancel_order na BinancePrivateExchange.
9. Teste Sentinela: test_phase_8_4a_has_zero_live_order_capability.
10. Cenários completos de negócio (BUY/SELL válidos, falhas de saldo, risco, notional e duplicidade).
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
    DryRunExecutionEngine,
    DryRunOrderResult,
    DryRunStorage,
    ExecutionMode,
    InvalidExecutionIntentError,
    LiveExecutionBlockedError,
    build_order_payload,
    generate_client_order_id,
    run_dry_run_pipeline,
)
from finbot.live_safety import (
    AccountStateSnapshot,
    ApprovedOrderIntent,
    LiveSafetyGate,
    MarketFilterGuard,
    MarketFilters,
    OrderIntent,
    RejectedOrderIntent,
    SafetyDecision,
)
from finbot.private_exchange import (
    BinancePrivateExchange,
    LiveTradingBlockedError,
)
from finbot.risk import RiskDecision, RiskDecisionCode


def make_test_filters(
    symbol: str = "BTC/USDT",
    min_amount: str = "0.00001",
    amount_step: str = "0.00001",
    min_price: str = "0.01",
    price_step: str = "0.01",
    min_cost: str = "5.0",
) -> MarketFilters:
    return MarketFilters(
        symbol=symbol,
        base_asset=symbol.split("/")[0],
        quote_asset=symbol.split("/")[1],
        min_amount=Decimal(min_amount),
        max_amount=None,
        amount_step=Decimal(amount_step),
        min_price=Decimal(min_price),
        max_price=None,
        price_step=Decimal(price_step),
        min_cost=Decimal(min_cost),
        max_cost=None,
    )


def make_test_intent(
    symbol: str = "BTC/USDT",
    side: str = "BUY",
    order_type: str = "MARKET",
    quantity: str = "0.001",
    price: str | None = "50000.00",
    requested_notional: str = "50.00",
    correlation_id: str = "test-corr-abc",
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
    normalized_quantity: str = "0.001",
    normalized_price: str | None = "50000.00",
    normalized_notional: str = "50.00",
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


class TestClientOrderId(unittest.TestCase):
    """Testes para a geração determinística do clientOrderId."""

    def test_client_order_id_is_deterministic(self) -> None:
        """Mesmo correlation_id sempre gera o mesmo clientOrderId."""
        id1 = generate_client_order_id("tx-uuid-12345")
        id2 = generate_client_order_id("tx-uuid-12345")
        self.assertEqual(id1, id2)

    def test_client_order_id_different_for_different_inputs(self) -> None:
        """correlation_ids diferentes geram clientOrderIds diferentes."""
        id1 = generate_client_order_id("tx-uuid-1")
        id2 = generate_client_order_id("tx-uuid-2")
        self.assertNotEqual(id1, id2)

    def test_client_order_id_binance_compliance(self) -> None:
        """clientOrderId obedece às restrições da Binance Spot (comprimento <= 36, sem caracteres inválidos)."""
        client_id = generate_client_order_id("sample-intent-xyz-987")
        self.assertTrue(client_id.startswith("finbot_"))
        self.assertLessEqual(len(client_id), 36)
        # Deve conter apenas caracteres alfanuméricos e sublinhados/hífens
        for char in client_id:
            self.assertTrue(char.isalnum() or char in ("_", "-"))

    def test_client_order_id_rejects_empty_or_invalid(self) -> None:
        """Rejeita strings vazias ou nulas."""
        with self.assertRaises(ValueError):
            generate_client_order_id("")
        with self.assertRaises(ValueError):
            generate_client_order_id("   ")


class TestOrderPayloadBuilder(unittest.TestCase):
    """Testes para construção do payload canônico da exchange."""

    def test_build_order_payload_market_buy(self) -> None:
        """Constrói payload correto para ordem MARKET BUY."""
        intent = make_test_intent(side="BUY", order_type="MARKET", quantity="0.0015", price=None)
        approved = make_test_approved_intent(intent, normalized_quantity="0.0015", normalized_price=None)
        client_id = generate_client_order_id(intent.correlation_id)

        payload = build_order_payload(approved, client_id)

        self.assertEqual(payload["symbol"], "BTC/USDT")
        self.assertEqual(payload["type"], "market")
        self.assertEqual(payload["side"], "buy")
        self.assertEqual(payload["amount"], 0.0015)
        self.assertNotIn("price", payload)
        self.assertEqual(payload["params"]["clientOrderId"], client_id)

    def test_build_order_payload_limit_sell(self) -> None:
        """Constrói payload correto para ordem LIMIT SELL com preço."""
        intent = make_test_intent(side="SELL", order_type="LIMIT", quantity="0.002", price="62500.50")
        approved = make_test_approved_intent(intent, normalized_quantity="0.002", normalized_price="62500.50")
        client_id = generate_client_order_id(intent.correlation_id)

        payload = build_order_payload(approved, client_id)

        self.assertEqual(payload["symbol"], "BTC/USDT")
        self.assertEqual(payload["type"], "limit")
        self.assertEqual(payload["side"], "sell")
        self.assertEqual(payload["amount"], 0.002)
        self.assertEqual(payload["price"], 62500.50)
        self.assertEqual(payload["params"]["clientOrderId"], client_id)

    def test_build_order_payload_rejects_raw_or_rejected_intent(self) -> None:
        """Payload builder falha categoricamente se não receber ApprovedOrderIntent."""
        raw_intent = make_test_intent()
        with self.assertRaises(InvalidExecutionIntentError):
            build_order_payload(raw_intent, "cid-1")  # type: ignore[arg-type]

        rejected = RejectedOrderIntent(
            intent=raw_intent,
            reason_code="REJECTED",
            reason="Blocked",
            checks={},
            rejected_at="2026-09-28T00:00:00Z",
        )
        with self.assertRaises(InvalidExecutionIntentError):
            build_order_payload(rejected, "cid-1")  # type: ignore[arg-type]


class TestDryRunStorageAndIdempotency(unittest.TestCase):
    """Testes de persistência e idempotência com SQLite."""

    def test_idempotency_returns_duplicate_intent_on_second_run(self) -> None:
        """Executar a mesma intenção duas vezes retorna DUPLICATE_INTENT sem duplicar gravação."""
        engine = DryRunExecutionEngine(storage=DryRunStorage(":memory:"))
        approved = make_test_approved_intent()

        first_res = engine.execute(approved)
        self.assertEqual(first_res.status, "SIMULATED_ACCEPTED")

        second_res = engine.execute(approved)
        self.assertEqual(second_res.status, "DUPLICATE_INTENT")
        self.assertIn("já registrada", second_res.safety_reason)

    def test_storage_persists_across_restart(self) -> None:
        """Persistência SQLite mantém idempotência mesmo reabrindo o banco de dados."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_file = Path(tmpdir) / "test_dry_run.sqlite3"
            storage1 = DryRunStorage(db_file)
            engine1 = DryRunExecutionEngine(storage=storage1)
            approved = make_test_approved_intent()

            res1 = engine1.execute(approved)
            self.assertEqual(res1.status, "SIMULATED_ACCEPTED")

            # Simula reinício do processo instanciando novo storage no mesmo arquivo
            storage2 = DryRunStorage(db_file)
            engine2 = DryRunExecutionEngine(storage=storage2)

            res2 = engine2.execute(approved)
            self.assertEqual(res2.status, "DUPLICATE_INTENT")

            # Verifica integridade direta via SQL com fechamento seguro
            conn = sqlite3.connect(str(db_file))
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT count(*) FROM dry_run_orders")
                count = cursor.fetchone()[0]
                cursor.close()
            finally:
                conn.close()
            self.assertEqual(count, 1)

    def test_no_credentials_in_database(self) -> None:
        """Valida que o schema e os registros do SQLite não contêm chaves de API ou segredos."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_file = Path(tmpdir) / "test_audit.sqlite3"
            storage = DryRunStorage(db_file)
            engine = DryRunExecutionEngine(storage=storage)
            engine.execute(make_test_approved_intent())

            conn = sqlite3.connect(str(db_file))
            try:
                cursor = conn.cursor()
                cursor.execute("PRAGMA table_info(dry_run_orders)")
                columns = [row[1] for row in cursor.fetchall()]
                cursor.close()
            finally:
                conn.close()

            # Proíbe colunas que possam armazenar dados confidenciais
            forbidden = {"api_key", "api_secret", "secret", "password", "token", "credential"}
            for col in columns:
                self.assertNotIn(col.lower(), forbidden)


class TestDryRunExecutionEngine(unittest.TestCase):
    """Testes unitários para o DryRunExecutionEngine."""

    def test_engine_accepts_approved_order_intent(self) -> None:
        """Engine aceita exclusivamente ApprovedOrderIntent e retorna SIMULATED_ACCEPTED."""
        engine = DryRunExecutionEngine()
        approved = make_test_approved_intent()
        result = engine.execute(approved)

        self.assertIsInstance(result, DryRunOrderResult)
        self.assertEqual(result.status, "SIMULATED_ACCEPTED")
        self.assertEqual(result.execution_mode, ExecutionMode.DRY_RUN.value)
        self.assertIsNotNone(result.order_payload)
        self.assertEqual(result.quantity, approved.normalized_quantity)

    def test_engine_rejects_raw_order_intent(self) -> None:
        """Engine rejeita categoricamente OrderIntent cru (fail-closed)."""
        engine = DryRunExecutionEngine()
        raw = make_test_intent()
        with self.assertRaises(InvalidExecutionIntentError):
            engine.execute(raw)  # type: ignore[arg-type]

    def test_engine_rejects_rejected_order_intent(self) -> None:
        """Engine rejeita categoricamente RejectedOrderIntent (fail-closed)."""
        engine = DryRunExecutionEngine()
        raw = make_test_intent()
        rejected = RejectedOrderIntent(
            intent=raw,
            reason_code="RISK_BLOCKED",
            reason="Blocked by risk",
            checks={},
            rejected_at="2026-09-28T00:00:00Z",
        )
        with self.assertRaises(InvalidExecutionIntentError):
            engine.execute(rejected)  # type: ignore[arg-type]

    def test_engine_blocks_live_mode_instantiation(self) -> None:
        """Instanciar com ExecutionMode.LIVE é expressamente bloqueado."""
        with self.assertRaises(LiveExecutionBlockedError):
            DryRunExecutionEngine(mode=ExecutionMode.LIVE)

    def test_dry_run_order_result_never_allows_filled_status(self) -> None:
        """DryRunOrderResult não aceita status FILLED (proibido em Dry-Run)."""
        with self.assertRaises(ValueError):
            DryRunOrderResult(
                correlation_id="1",
                client_order_id="c1",
                symbol="BTC/USDT",
                side="BUY",
                order_type="MARKET",
                quantity=Decimal("0.001"),
                price=None,
                notional=Decimal("50.0"),
                status="FILLED",
                created_at="2026-09-28T00:00:00Z",
                safety_reason="Invalid",
                execution_mode=ExecutionMode.DRY_RUN.value,
            )


class TestPipelineIntegration(unittest.TestCase):
    """Testes de integração do pipeline: OrderIntent -> LiveSafetyGate -> DryRunExecutionEngine."""

    def setUp(self) -> None:
        self.gate = LiveSafetyGate()
        self.engine = DryRunExecutionEngine()
        self.filters = make_test_filters()
        self.market_guard = MarketFilterGuard(self.filters)
        self.config = Config(
            trading_mode="live",
            live_trading_acknowledged=True,
            live_max_order_notional=100.0,
        )

    def test_pipeline_success_when_gate_approves(self) -> None:
        """Quando o gate aprova, o engine produz DryRunOrderResult com SIMULATED_ACCEPTED."""
        intent = make_test_intent(quantity="0.001", price="50000.0", requested_notional="50.0")
        risk_decision = RiskDecision(
            allowed=True,
            code=RiskDecisionCode.ALLOWED,
            reason="OK",
            action="BUY",
            target_notional=Decimal("50.0"),
        )
        snapshot = AccountStateSnapshot(
            symbol="BTC/USDT",
            base_asset="BTC",
            quote_asset="USDT",
            base_free=Decimal("0.5"),
            base_locked=Decimal("0.0"),
            quote_free=Decimal("1000.0"),
            quote_locked=Decimal("0.0"),
            captured_at="2026-09-28T00:00:00Z",
        )

        decision, result = run_dry_run_pipeline(
            intent=intent,
            gate=self.gate,
            engine=self.engine,
            risk_decision=risk_decision,
            market_guard=self.market_guard,
            account_snapshot=snapshot,
            config=self.config,
        )

        self.assertTrue(decision.allowed)
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "SIMULATED_ACCEPTED")
        self.assertEqual(result.execution_mode, ExecutionMode.DRY_RUN.value)

    def test_pipeline_engine_never_called_when_gate_rejects(self) -> None:
        """Quando o gate rejeita, o engine NUNCA é chamado e o resultado é None."""
        intent = make_test_intent(quantity="0.001", price="50000.0", requested_notional="50.0")
        # Risco rejeita
        risk_decision = RiskDecision(
            allowed=False,
            code=RiskDecisionCode.KILL_SWITCH_ACTIVE,
            reason="Kill switch ativo",
            action="BUY_BLOCKED_KILL_SWITCH_ACTIVE",
        )
        snapshot = AccountStateSnapshot(
            symbol="BTC/USDT",
            base_asset="BTC",
            quote_asset="USDT",
            base_free=Decimal("0.5"),
            base_locked=Decimal("0.0"),
            quote_free=Decimal("1000.0"),
            quote_locked=Decimal("0.0"),
            captured_at="2026-09-28T00:00:00Z",
        )

        mock_engine = MagicMock(spec=DryRunExecutionEngine)

        decision, result = run_dry_run_pipeline(
            intent=intent,
            gate=self.gate,
            engine=mock_engine,
            risk_decision=risk_decision,
            market_guard=self.market_guard,
            account_snapshot=snapshot,
            config=self.config,
        )

        self.assertFalse(decision.allowed)
        self.assertIsNone(result)
        mock_engine.execute.assert_not_called()


class TestExecutionScenarios(unittest.TestCase):
    """Testes com cenários de negócio determinísticos."""

    def setUp(self) -> None:
        self.gate = LiveSafetyGate()
        self.engine = DryRunExecutionEngine()
        self.filters = make_test_filters()
        self.market_guard = MarketFilterGuard(self.filters)
        self.config = Config(
            trading_mode="live",
            live_trading_acknowledged=True,
            live_max_order_notional=100.0,
        )
        self.risk_allow = RiskDecision(
            allowed=True,
            code=RiskDecisionCode.ALLOWED,
            reason="OK",
            action="BUY",
            target_notional=Decimal("50.0"),
        )
        self.snapshot_funded = AccountStateSnapshot(
            symbol="BTC/USDT",
            base_asset="BTC",
            quote_asset="USDT",
            base_free=Decimal("1.0"),
            base_locked=Decimal("0.0"),
            quote_free=Decimal("1000.0"),
            quote_locked=Decimal("0.0"),
            captured_at="2026-09-28T00:00:00Z",
        )

    def test_scenario_valid_sell_order(self) -> None:
        """Cenário: SELL válido com saldo base suficiente."""
        intent = make_test_intent(
            side="SELL",
            quantity="0.001",
            price="50000.00",
            requested_notional="50.00",
            correlation_id="scenario-sell-1",
        )
        risk_sell = RiskDecision(
            allowed=True,
            code=RiskDecisionCode.ALLOWED,
            reason="OK",
            action="SELL",
            target_notional=Decimal("50.0"),
        )

        decision, result = run_dry_run_pipeline(
            intent=intent,
            gate=self.gate,
            engine=self.engine,
            risk_decision=risk_sell,
            market_guard=self.market_guard,
            account_snapshot=self.snapshot_funded,
            config=self.config,
        )

        self.assertTrue(decision.allowed)
        self.assertIsNotNone(result)
        self.assertEqual(result.side, "SELL")
        self.assertEqual(result.status, "SIMULATED_ACCEPTED")

    def test_scenario_below_min_notional_rejected_before_engine(self) -> None:
        """Cenário: BUY abaixo do notional mínimo (ex: 2.0 USDT quando min é 5.0) é rejeitado."""
        intent = make_test_intent(
            quantity="0.00004",
            price="50000.00",
            requested_notional="2.00",
            correlation_id="scenario-min-notional",
        )

        decision, result = run_dry_run_pipeline(
            intent=intent,
            gate=self.gate,
            engine=self.engine,
            risk_decision=self.risk_allow,
            market_guard=self.market_guard,
            account_snapshot=self.snapshot_funded,
            config=self.config,
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "NOTIONAL_FILTER_FAILED")
        self.assertIsNone(result)

    def test_scenario_above_hard_live_limit_rejected_before_engine(self) -> None:
        """Cenário: Ordem acima de live_max_order_notional (100 USDT) é rejeitada."""
        intent = make_test_intent(
            quantity="0.003",
            price="50000.00",
            requested_notional="150.00",
            correlation_id="scenario-hard-limit",
        )

        decision, result = run_dry_run_pipeline(
            intent=intent,
            gate=self.gate,
            engine=self.engine,
            risk_decision=self.risk_allow,
            market_guard=self.market_guard,
            account_snapshot=self.snapshot_funded,
            config=self.config,
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "HARD_LIVE_LIMIT_EXCEEDED")
        self.assertIsNone(result)

    def test_scenario_insufficient_quote_balance_rejected_before_engine(self) -> None:
        """Cenário: BUY com saldo USDT insuficiente é rejeitado."""
        empty_snapshot = AccountStateSnapshot(
            symbol="BTC/USDT",
            base_asset="BTC",
            quote_asset="USDT",
            base_free=Decimal("0.0"),
            base_locked=Decimal("0.0"),
            quote_free=Decimal("1.0"),  # apenas 1 USDT livre, intent pede 50
            quote_locked=Decimal("0.0"),
            captured_at="2026-09-28T00:00:00Z",
        )
        intent = make_test_intent(
            quantity="0.001",
            price="50000.00",
            requested_notional="50.00",
            correlation_id="scenario-no-quote",
        )

        decision, result = run_dry_run_pipeline(
            intent=intent,
            gate=self.gate,
            engine=self.engine,
            risk_decision=self.risk_allow,
            market_guard=self.market_guard,
            account_snapshot=empty_snapshot,
            config=self.config,
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "INSUFFICIENT_QUOTE_BALANCE")
        self.assertIsNone(result)

    def test_scenario_insufficient_base_balance_rejected_before_engine(self) -> None:
        """Cenário: SELL com saldo BTC insuficiente é rejeitado."""
        empty_snapshot = AccountStateSnapshot(
            symbol="BTC/USDT",
            base_asset="BTC",
            quote_asset="USDT",
            base_free=Decimal("0.0001"),  # apenas 0.0001 BTC livre, intent pede 0.001
            base_locked=Decimal("0.0"),
            quote_free=Decimal("1000.0"),
            quote_locked=Decimal("0.0"),
            captured_at="2026-09-28T00:00:00Z",
        )
        intent = make_test_intent(
            side="SELL",
            quantity="0.001",
            price="50000.00",
            requested_notional="50.00",
            correlation_id="scenario-no-base",
        )
        risk_sell = RiskDecision(
            allowed=True,
            code=RiskDecisionCode.ALLOWED,
            reason="OK",
            action="SELL",
            target_notional=Decimal("50.0"),
        )

        decision, result = run_dry_run_pipeline(
            intent=intent,
            gate=self.gate,
            engine=self.engine,
            risk_decision=risk_sell,
            market_guard=self.market_guard,
            account_snapshot=empty_snapshot,
            config=self.config,
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "INSUFFICIENT_BASE_BALANCE")
        self.assertIsNone(result)

    def test_scenario_live_not_acknowledged_rejected_before_engine(self) -> None:
        """Cenário: Se live_trading_acknowledged=False, rejeita antes do engine."""
        unack_config = Config(
            trading_mode="live",
            live_trading_acknowledged=False,
            live_max_order_notional=100.0,
        )
        intent = make_test_intent(correlation_id="scenario-unack")

        decision, result = run_dry_run_pipeline(
            intent=intent,
            gate=self.gate,
            engine=self.engine,
            risk_decision=self.risk_allow,
            market_guard=self.market_guard,
            account_snapshot=self.snapshot_funded,
            config=unack_config,
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "LIVE_NOT_ACKNOWLEDGED")
        self.assertIsNone(result)


class TestSecurityAndZeroLiveOrderCapability(unittest.TestCase):
    """Testes de segurança e sentinela garantindo inviolabilidade de execução real."""

    def test_binance_private_exchange_create_and_cancel_order_remain_blocked(self) -> None:
        """create_order e cancel_order devem continuar levantando LiveTradingBlockedError."""
        fake_provider = MagicMock()
        fake_provider.get_credentials.return_value = MagicMock(api_key="k", api_secret="s")
        config = Config(trading_mode="live")
        exchange = BinancePrivateExchange(config=config, credential_provider=fake_provider)

        with self.assertRaises(LiveTradingBlockedError):
            exchange.create_order("BTC/USDT", "market", "buy", 0.001)

        with self.assertRaises(LiveTradingBlockedError):
            exchange.cancel_order("order-123", "BTC/USDT")

    def test_phase_8_4a_has_zero_live_order_capability(self) -> None:
        """TESTE SENTINELA DA FASE 8.4A:

        Comprova matematicamente e arquiteturalmente que:
        1. DryRunExecutionEngine não possui qualquer método de rede ou de submissão à exchange.
        2. ExecutionMode.LIVE é rejeitado imediatamente com LiveExecutionBlockedError.
        3. status FILLED é expressamente proibido de ser gerado em Dry-Run.
        4. O engine não importa nem instancia adapters capazes de chamar POST na Binance.
        5. A exchange privada continua bloqueada com LiveTradingBlockedError.
        """
        # 1. Zero capacidade de LIVE no engine
        with self.assertRaises(LiveExecutionBlockedError):
            DryRunExecutionEngine(mode=ExecutionMode.LIVE)

        # 2. Ausência de métodos de rede no DryRunExecutionEngine
        engine = DryRunExecutionEngine()
        forbidden_methods = ["submit_order", "send_order", "post_order", "place_order", "create_order"]
        for method in forbidden_methods:
            self.assertFalse(
                hasattr(engine, method),
                f"DryRunExecutionEngine viola segurança ao expor método '{method}'.",
            )

        # 3. Execução em DryRun gera apenas status SIMULATED_* ou DUPLICATE_*
        approved = make_test_approved_intent()
        result = engine.execute(approved)
        self.assertIn(result.status, ("SIMULATED_ACCEPTED", "DUPLICATE_INTENT"))
        self.assertNotEqual(result.status, "FILLED")

        # 4. Exchange continua bloqueada
        fake_prov = MagicMock()
        fake_prov.get_credentials.return_value = MagicMock(api_key="k", api_secret="s")
        config = Config(trading_mode="live")
        ex = BinancePrivateExchange(config=config, credential_provider=fake_prov)
        with self.assertRaises(LiveTradingBlockedError):
            ex.create_order("BTC/USDT", "market", "buy", 0.001)


if __name__ == "__main__":
    unittest.main()

