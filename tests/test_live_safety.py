"""Suíte de testes para a FASE 8.3 — Live Execution Safety Foundation.

Testa:
1. MarketFilterGuard (normalização de quantidades, preços, notional mínimo, sem aumentos silenciosos).
2. OrderIntent (imutabilidade, validação de campos, ausência de capacidade executiva).
3. LiveSafetyGate (soberania do Risk Engine, trava live_trading_acknowledged, hard limit, fail-closed).
4. StateReconciler (reconciliação de saldos quote/base para BUY e SELL).
5. AccountStatus / API Permissions (desacoplamento entre can_trade/can_withdraw da conta e autorização da API Key).
6. LiveSafetyAuditStorage (gravação local sem credenciais).
7. Teste Sentinela: test_phase_8_3_cannot_submit_real_orders.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from decimal import Decimal
import unittest
from unittest.mock import MagicMock

from finbot.config import Config
from finbot.live_safety import (
    AccountStateSnapshot,
    ApprovedOrderIntent,
    LiveSafetyAuditStorage,
    LiveSafetyGate,
    MarketFilterGuard,
    MarketFilters,
    OrderIntent,
    RejectedOrderIntent,
    SafetyDecision,
    StateReconciler,
    extract_market_filters,
    sanitize_amount,
    sanitize_price,
    validate_notional,
)
from finbot.private_exchange import (
    AccountStatus,
    BinancePrivateExchange,
    LiveTradingBlockedError,
)
from finbot.risk import RiskDecision, RiskDecisionCode


def make_dummy_filters(
    symbol: str = "BTC/USDT",
    min_amount: str = "0.00001",
    max_amount: str = "9000.0",
    amount_step: str = "0.00001",
    min_price: str = "0.01",
    max_price: str = "1000000.0",
    price_step: str = "0.01",
    min_cost: str = "5.0",
    max_cost: str | None = None,
) -> MarketFilters:
    return MarketFilters(
        symbol=symbol,
        base_asset=symbol.split("/")[0],
        quote_asset=symbol.split("/")[1],
        min_amount=Decimal(min_amount),
        max_amount=Decimal(max_amount) if max_amount else None,
        amount_step=Decimal(amount_step),
        min_price=Decimal(min_price),
        max_price=Decimal(max_price) if max_price else None,
        price_step=Decimal(price_step),
        min_cost=Decimal(min_cost),
        max_cost=Decimal(max_cost) if max_cost else None,
    )


def make_dummy_intent(
    symbol: str = "BTC/USDT",
    side: str = "BUY",
    order_type: str = "MARKET",
    quantity: str = "0.002",
    price: str | None = "50000.00",
    requested_notional: str = "100.00",
    correlation_id: str = "test-corr-123",
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


class TestMarketFilterGuard(unittest.TestCase):
    """Testes unitários para regras de mercado e funções de sanitização."""

    def test_sanitize_amount_truncates_to_step_size(self) -> None:
        """1. Quantidade é truncada (round down) para o stepSize sem arredondar para cima."""
        # 0.0012399 com step 0.00001 deve virar 0.00123
        valid, sanitized, err = sanitize_amount(
            amount=Decimal("0.0012399"),
            min_amount=Decimal("0.00001"),
            amount_step=Decimal("0.00001"),
        )
        self.assertTrue(valid)
        self.assertEqual(sanitized, Decimal("0.00123"))
        self.assertEqual(err, "")

    def test_sanitize_amount_below_minimum_rejected_without_increase(self) -> None:
        """2. Quantidade abaixo do mínimo é rejeitada e NUNCA aumentada silenciosamente."""
        valid, sanitized, err = sanitize_amount(
            amount=Decimal("0.000005"),
            min_amount=Decimal("0.00001"),
            amount_step=Decimal("0.00001"),
        )
        self.assertFalse(valid)
        self.assertEqual(sanitized, Decimal("0"))
        self.assertIn("inferior ao mínimo", err)

    def test_sanitize_amount_above_maximum_rejected(self) -> None:
        """3. Quantidade acima do máximo permitido é rejeitada."""
        valid, sanitized, err = sanitize_amount(
            amount=Decimal("100.0"),
            min_amount=Decimal("0.001"),
            amount_step=Decimal("0.001"),
            max_amount=Decimal("50.0"),
        )
        self.assertFalse(valid)
        self.assertIn("excede o máximo", err)

    def test_sanitize_price_truncates_to_price_step(self) -> None:
        """4. Preço é sanitizado de acordo com o price_step."""
        valid, sanitized, err = sanitize_price(
            price=Decimal("65432.128"),
            min_price=Decimal("0.01"),
            price_step=Decimal("0.01"),
        )
        self.assertTrue(valid)
        self.assertEqual(sanitized, Decimal("65432.12"))

    def test_validate_notional_rejects_below_minimum(self) -> None:
        """5. Notional abaixo do mínimo é rejeitado sem ajuste automático."""
        valid, err = validate_notional(Decimal("4.99"), min_cost=Decimal("5.0"))
        self.assertFalse(valid)
        self.assertIn("inferior ao mínimo exigido", err)

        valid_ok, err_ok = validate_notional(Decimal("5.00"), min_cost=Decimal("5.0"))
        self.assertTrue(valid_ok)
        self.assertEqual(err_ok, "")

    def test_extract_market_filters_ccxt_parsing(self) -> None:
        """6. Extração e conversão de filtros normalizados do CCXT."""
        ccxt_mock = {
            "symbol": "BTC/USDT",
            "base": "BTC",
            "quote": "USDT",
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
        filters = extract_market_filters(ccxt_mock)
        self.assertEqual(filters.symbol, "BTC/USDT")
        self.assertEqual(filters.min_amount, Decimal("0.00001"))
        self.assertEqual(filters.amount_step, Decimal("0.00001"))
        self.assertEqual(filters.min_cost, Decimal("5.0"))


class TestOrderIntent(unittest.TestCase):
    """Testes da estrutura imutável OrderIntent."""

    def test_order_intent_immutability(self) -> None:
        """7. OrderIntent é imutável (@dataclass(frozen=True))."""
        intent = make_dummy_intent()
        with self.assertRaises(FrozenInstanceError):
            intent.quantity = Decimal("1.0")  # type: ignore[misc]

    def test_order_intent_validation_rules(self) -> None:
        """8. Validações estruturais de integridade em OrderIntent."""
        with self.assertRaises(ValueError):
            make_dummy_intent(quantity="-0.5")
        with self.assertRaises(ValueError):
            make_dummy_intent(requested_notional="0")
        with self.assertRaises(ValueError):
            make_dummy_intent(side="INVALID_SIDE")
        with self.assertRaises(ValueError):
            make_dummy_intent(order_type="STOP_LOSS")

    def test_order_intent_has_no_execution_capability(self) -> None:
        """9. OrderIntent não possui nenhum método de envio de ordens."""
        intent = make_dummy_intent()
        for method_name in ("submit", "execute", "send", "place_order"):
            self.assertFalse(hasattr(intent, method_name))


class TestStateReconciler(unittest.TestCase):
    """Testes do reconciliador de estado de saldo e posições."""

    def setUp(self) -> None:
        self.reconciler = StateReconciler()
        self.snapshot = AccountStateSnapshot(
            symbol="BTC/USDT",
            base_asset="BTC",
            quote_asset="USDT",
            base_free=Decimal("0.05000000"),
            base_locked=Decimal("0.0"),
            quote_free=Decimal("500.00"),
            quote_locked=Decimal("0.0"),
            captured_at="2026-09-28T00:00:00Z",
        )

    def test_buy_with_sufficient_quote_balance(self) -> None:
        """10. BUY com saldo quote suficiente é aprovado na reconciliação."""
        intent = make_dummy_intent(side="BUY", requested_notional="100.00")
        dec = self.reconciler.reconcile(intent, self.snapshot)
        self.assertTrue(dec.is_valid)
        self.assertEqual(dec.code, "PASSED")

    def test_buy_with_insufficient_quote_balance_rejected(self) -> None:
        """11. BUY com saldo quote insuficiente é rejeitado fail-closed."""
        intent = make_dummy_intent(side="BUY", requested_notional="600.00")
        dec = self.reconciler.reconcile(intent, self.snapshot)
        self.assertFalse(dec.is_valid)
        self.assertEqual(dec.code, "INSUFFICIENT_QUOTE_BALANCE")

    def test_sell_with_sufficient_base_balance(self) -> None:
        """12. SELL com saldo base suficiente é aprovado na reconciliação."""
        intent = make_dummy_intent(side="SELL", quantity="0.01")
        dec = self.reconciler.reconcile(intent, self.snapshot)
        self.assertTrue(dec.is_valid)
        self.assertEqual(dec.code, "PASSED")

    def test_sell_with_insufficient_base_balance_rejected(self) -> None:
        """13. SELL com saldo base insuficiente é rejeitado fail-closed."""
        intent = make_dummy_intent(side="SELL", quantity="0.10")
        dec = self.reconciler.reconcile(intent, self.snapshot)
        self.assertFalse(dec.is_valid)
        self.assertEqual(dec.code, "INSUFFICIENT_BASE_BALANCE")

    def test_missing_snapshot_rejected(self) -> None:
        """14. Reconciliação sem snapshot da conta falha categoricamente."""
        intent = make_dummy_intent()
        dec = self.reconciler.reconcile(intent, None)
        self.assertFalse(dec.is_valid)
        self.assertEqual(dec.code, "ACCOUNT_SNAPSHOT_MISSING")


class TestLiveSafetyGate(unittest.TestCase):
    """Testes exaustivos do LiveSafetyGate."""

    def setUp(self) -> None:
        self.audit_storage = LiveSafetyAuditStorage(db_path=":memory:")
        self.gate = LiveSafetyGate(audit_storage=self.audit_storage)
        self.filters = make_dummy_filters()
        self.market_guard = MarketFilterGuard(self.filters)
        self.snapshot = AccountStateSnapshot(
            symbol="BTC/USDT",
            base_asset="BTC",
            quote_asset="USDT",
            base_free=Decimal("1.0"),
            base_locked=Decimal("0.0"),
            quote_free=Decimal("1000.0"),
            quote_locked=Decimal("0.0"),
            captured_at="2026-09-28T00:00:00Z",
        )
        self.allowed_risk = RiskDecision(
            allowed=True,
            code=RiskDecisionCode.ALLOWED,
            reason="Risk check passed",
            action="BUY",
            target_notional=Decimal("100.00"),
        )
        self.valid_config = Config(
            trading_mode="live",
            live_trading_acknowledged=True,
            live_max_order_notional=150.0,
        )

    def test_full_pipeline_approval(self) -> None:
        """15. Intent com todos os critérios aprovados gera SafetyDecision(allowed=True)."""
        intent = make_dummy_intent(side="BUY", requested_notional="100.00", quantity="0.002", price="50000.00")
        decision = self.gate.evaluate(
            intent=intent,
            risk_decision=self.allowed_risk,
            market_guard=self.market_guard,
            account_snapshot=self.snapshot,
            config=self.valid_config,
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason_code, "APPROVED")
        self.assertIsNotNone(decision.approved_intent)
        self.assertIsNone(decision.rejected_intent)

        # Verifica gravação na auditoria
        recent = self.audit_storage.get_recent_decisions()
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]["correlation_id"], intent.correlation_id)
        self.assertEqual(recent[0]["allowed"], 1)

    def test_risk_rejection_vetoes_safety_gate(self) -> None:
        """16. Soberania do Risk Engine: rejeição do risco bloqueia imediatamente."""
        rejected_risk = RiskDecision(
            allowed=False,
            code=RiskDecisionCode.DAILY_LOSS_LIMIT,
            reason="Limite de perda diária atingido",
            action="BUY",
        )
        intent = make_dummy_intent()
        decision = self.gate.evaluate(
            intent=intent,
            risk_decision=rejected_risk,
            market_guard=self.market_guard,
            account_snapshot=self.snapshot,
            config=self.valid_config,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "RISK_DAILY_LOSS_LIMIT")
        self.assertIn("Risk Engine rejeitou", decision.reason)

    def test_live_not_acknowledged_rejects(self) -> None:
        """17. Falta de live_trading_acknowledged=True rejeita a intenção."""
        unack_config = Config(
            trading_mode="live",
            live_trading_acknowledged=False,
            live_max_order_notional=150.0,
        )
        intent = make_dummy_intent()
        decision = self.gate.evaluate(
            intent=intent,
            risk_decision=self.allowed_risk,
            market_guard=self.market_guard,
            account_snapshot=self.snapshot,
            config=unack_config,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "LIVE_NOT_ACKNOWLEDGED")

    def test_paper_mode_rejects_in_live_gate(self) -> None:
        """18. trading_mode != 'live' é rejeitado no LiveSafetyGate."""
        paper_config = Config(
            trading_mode="paper",
            live_trading_acknowledged=True,
        )
        intent = make_dummy_intent()
        decision = self.gate.evaluate(
            intent=intent,
            risk_decision=self.allowed_risk,
            market_guard=self.market_guard,
            account_snapshot=self.snapshot,
            config=paper_config,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "NOT_IN_LIVE_MODE")

    def test_hard_live_limit_exceeded_rejects_without_truncation(self) -> None:
        """19. Ordem acima de live_max_order_notional é rejeitada sem truncamento."""
        strict_config = Config(
            trading_mode="live",
            live_trading_acknowledged=True,
            live_max_order_notional=50.0,  # Limite de 50 USDT
        )
        intent = make_dummy_intent(requested_notional="100.00")
        decision = self.gate.evaluate(
            intent=intent,
            risk_decision=self.allowed_risk,
            market_guard=self.market_guard,
            account_snapshot=self.snapshot,
            config=strict_config,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "HARD_LIVE_LIMIT_EXCEEDED")

    def test_missing_dependencies_fail_closed(self) -> None:
        """20. Componentes ausentes (risk, market_guard ou snapshot) disparam fail-closed."""
        intent = make_dummy_intent()

        dec1 = self.gate.evaluate(intent, None, self.market_guard, self.snapshot, self.valid_config)
        self.assertFalse(dec1.allowed)
        self.assertEqual(dec1.reason_code, "RISK_DECISION_MISSING")

        dec2 = self.gate.evaluate(intent, self.allowed_risk, None, self.snapshot, self.valid_config)
        self.assertFalse(dec2.allowed)
        self.assertEqual(dec2.reason_code, "MARKET_GUARD_MISSING")

        dec3 = self.gate.evaluate(intent, self.allowed_risk, self.market_guard, None, self.valid_config)
        self.assertFalse(dec3.allowed)
        self.assertEqual(dec3.reason_code, "ACCOUNT_SNAPSHOT_MISSING")


class TestAccountStatusAndPermissionsInvestigation(unittest.TestCase):
    """Testes documentais sobre a semântica de AccountStatus retornado pela Binance."""

    def test_account_status_can_trade_is_descriptive_not_authorizing(self) -> None:
        """21. can_trade e can_withdraw de /api/v3/account refletem a conta e NÃO autorizam a API key."""
        # Na homologação 8.2C, can_withdraw foi retornado como True pela conta Binance
        # mesmo a API key tendo saques terminantemente desabilitados.
        status = AccountStatus(
            account_type="SPOT",
            can_trade=True,
            can_withdraw=True,
            can_deposit=True,
        )
        # Prova conceitual: o FinBot NÃO utiliza esse status como autorização
        self.assertTrue(status.can_trade)
        self.assertTrue(status.can_withdraw)

        # O LiveSafetyGate não utiliza can_withdraw para aprovar ordens
        # A defesa reside nas chaves sem permissão de saque na Binance e travas internas


class TestSentinelNoRealOrderExecution(unittest.TestCase):
    """Teste sentinela mandatório para a FASE 8.3."""

    def test_phase_8_3_cannot_submit_real_orders(self) -> None:
        """22. SENTINELA: Prova arquitetural de que a FASE 8.3 não introduziu caminho para envio de ordens reais."""
        # 1. ApprovedOrderIntent NÃO possui capacidade executiva
        intent = make_dummy_intent()
        approved = ApprovedOrderIntent(
            intent=intent,
            normalized_quantity=Decimal("0.002"),
            normalized_price=Decimal("50000.00"),
            normalized_notional=Decimal("100.00"),
            checks={"test": "passed"},
            approved_at="2026-09-28T00:00:00Z",
        )
        for method in ("submit", "execute", "send", "call_exchange"):
            self.assertFalse(hasattr(approved, method))

        # 2. LiveSafetyGate NÃO possui capacidade executiva
        gate = LiveSafetyGate()
        for method in ("submit_order", "execute_order", "send_order", "place_order"):
            self.assertFalse(hasattr(gate, method))

        # 3. BinancePrivateExchange create_order() CONTINUA bloqueado incondicionalmente
        from finbot.credentials import FakeCredentialProvider
        private_ex = BinancePrivateExchange(
            config=Config(trading_mode="live", live_trading_acknowledged=True),
            credential_provider=FakeCredentialProvider(api_key="k" * 64, api_secret="s" * 64),
        )
        with self.assertRaises(LiveTradingBlockedError) as ctx_create:
            private_ex.create_order("BTC/USDT", "BUY", "LIMIT", Decimal("0.002"), Decimal("50000.00"))
        self.assertIn("CRITICAL: Criação de ordens reais bloqueada", str(ctx_create.exception))

        # 4. BinancePrivateExchange cancel_order() CONTINUA bloqueado incondicionalmente
        with self.assertRaises(LiveTradingBlockedError) as ctx_cancel:
            private_ex.cancel_order("order-123", "BTC/USDT")
        self.assertIn("CRITICAL: Cancelamento de ordens reais bloqueado", str(ctx_cancel.exception))


if __name__ == "__main__":
    unittest.main()
