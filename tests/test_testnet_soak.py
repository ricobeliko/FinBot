"""Suíte de testes herméticos e determinísticos para Testnet Soak e Métricas Operacionais (FASE 8.4C2D).

Testa:
- Semântica de fills (average_fill_price = None quando executed_quantity == 0)
- Preservação separada de limit_price / requested_price
- Ordem cancelada não executada não afeta PnL
- Preenchimento parcial e preenchimento total
- Normalização de capital (TESTNET_STRATEGY_CAPITAL) independente do saldo da exchange
- Reinício seguro e recuperação de checkpoints
- Deduplicação de candles e prevenção de ordens repetidas
- Reconciliação prévia obrigatória após restart
- Tratamento de UNKNOWN e disparo de Circuit Breakers
- Bloqueio de novas ordens com Circuit Breaker armado
- Sentries de isolamento incondicional de Produção
- Modos Read-Only de Preview e Status sem exposição de segredos
- Zero chamadas de rede externas
"""

from datetime import datetime, timezone, timedelta
from decimal import Decimal
import io
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from finbot.config import Config
from finbot.credentials import WindowsCredentialProvider
from finbot.exchange import CandleData
from finbot.live_executor import (
    BinanceEnvironment,
    ExchangeOrderResult,
    FakeExchangeOrderAdapter,
    LiveOrderStorage,
    OrderStatus,
)
from finbot.strategy import Signal
from finbot.testnet_soak import (
    CircuitBreakerTrippedError,
    TestnetCircuitBreaker,
    TestnetFinancialMetrics,
    TestnetOperationalMetrics,
    TestnetPosition,
    TestnetSoakCycleResult,
    TestnetSoakSentryError,
    TestnetSoakStorage,
    TestnetTradeRecord,
    determine_runner_status,
    execute_testnet_soak_cycle,
    print_testnet_soak_status,
    recalculate_financial_metrics,
    reconcile_pre_cycle_state,
    run_testnet_soak_continuous,
    run_testnet_soak_preview,
    verify_testnet_soak_sentries,
)


class FakeCredentialProvider:
    def __init__(self, api_key: str = "test_key", api_secret: str = "test_secret", target_name: str = "FinBot/Binance/SpotTestnet") -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.target_name = target_name

    def get_credentials(self):
        class Creds:
            api_key = self.api_key
            api_secret = self.api_secret
        return Creds()


def generate_candles(prices: list[float], start_ts: int = 1700000000000, interval_ms: int = 60000) -> list[CandleData]:
    candles = []
    for i, p in enumerate(prices):
        ts = start_ts + (i * interval_ms)
        candles.append(
            CandleData(
                timestamp=ts,
                open=p,
                high=p + 10.0,
                low=p - 10.0,
                close=p,
                volume=1.0,
            )
        )
    return candles


class TestTestnetSoak(unittest.TestCase):
    """Testes unitários e de integração herméticos para o Testnet Soak."""

    def setUp(self) -> None:
        self.storage = TestnetSoakStorage(":memory:")
        self.order_storage = LiveOrderStorage(":memory:")
        self.fake_provider = FakeCredentialProvider()
        self.cfg = Config(
            trading_mode="live",
            binance_environment=BinanceEnvironment.SPOT_TESTNET,
            testnet_execution_enabled=True,
            live_execution_enabled=False,
            real_order_submission_enabled=False,
            testnet_strategy_capital=100.0,
            testnet_soak_db_path=":memory:",
            short_window=2,
            long_window=4,
            paper_timeframe="1m",
        )

    # =========================================================================
    # 1. SEMÂNTICA DE FILLS E QUALIDADE DE DADOS
    # =========================================================================

    def test_average_fill_price_none_when_unexecuted(self) -> None:
        """Quando executed_quantity == 0, average_fill_price é estritamente None."""
        res = ExchangeOrderResult(
            client_order_id="test_001",
            exchange_order_id="101",
            status=OrderStatus.ACKNOWLEDGED,
            symbol="BTC/USDT",
            side="BUY",
            order_type="LIMIT",
            requested_quantity=Decimal("0.00010000"),
            executed_quantity=Decimal("0.00000000"),
            cumulative_quote_quantity=Decimal("0.00"),
            average_price=Decimal("70521.36"),  # Mesmo se passado
            limit_price=Decimal("70521.36"),
        )
        self.assertIsNone(res.average_price)
        self.assertIsNone(res.average_fill_price)
        self.assertEqual(res.limit_price, Decimal("70521.36"))

    def test_canceled_unfilled_order_does_not_affect_pnl(self) -> None:
        """Ordem LIMIT cancelada sem fill não afeta saldo, posição nem PnL."""
        unfilled_canceled_trade = TestnetTradeRecord(
            client_order_id="c_unfilled_01",
            exchange_order_id="102",
            timestamp="2026-09-29T00:00:00Z",
            symbol="BTC/USDT",
            side="BUY",
            order_type="LIMIT",
            requested_quantity=Decimal("0.00010000"),
            executed_quantity=Decimal("0.00000000"),
            limit_price=Decimal("70521.36"),
            average_fill_price=None,
            notional=Decimal("0.00"),
            fee=Decimal("0.00"),
            fee_asset="USDT",
        )

        fin_m, pos = recalculate_financial_metrics(
            trades=[unfilled_canceled_trade],
            current_price=Decimal("80000.00"),
            strategy_capital=Decimal("100.00"),
        )

        self.assertEqual(fin_m.current_equity, Decimal("100.00"))
        self.assertEqual(fin_m.cash_balance, Decimal("100.00"))
        self.assertEqual(fin_m.realized_pnl, Decimal("0.00"))
        self.assertEqual(fin_m.unrealized_pnl, Decimal("0.00"))
        self.assertEqual(fin_m.net_pnl, Decimal("0.00"))
        self.assertEqual(fin_m.total_trades, 1)
        self.assertEqual(fin_m.closed_trades, 0)
        self.assertEqual(pos.side, "NONE")

    def test_full_fill_pnl_calculation(self) -> None:
        """Compra preenchida seguida de venda lucrativa calcula PnL realizado exato."""
        buy_trade = TestnetTradeRecord(
            client_order_id="b_01",
            exchange_order_id="201",
            timestamp="2026-09-29T00:00:00Z",
            symbol="BTC/USDT",
            side="BUY",
            order_type="MARKET",
            requested_quantity=Decimal("0.00010000"),
            executed_quantity=Decimal("0.00010000"),
            limit_price=None,
            average_fill_price=Decimal("60000.00"),
            notional=Decimal("6.00"),
            fee=Decimal("0.006"),
            fee_asset="USDT",
        )
        sell_trade = TestnetTradeRecord(
            client_order_id="s_01",
            exchange_order_id="202",
            timestamp="2026-09-29T00:05:00Z",
            symbol="BTC/USDT",
            side="SELL",
            order_type="MARKET",
            requested_quantity=Decimal("0.00010000"),
            executed_quantity=Decimal("0.00010000"),
            limit_price=None,
            average_fill_price=Decimal("66000.00"),  # +10%
            notional=Decimal("6.60"),
            fee=Decimal("0.0066"),
            fee_asset="USDT",
            realized_pnl=Decimal("0.5874"),  # 6.60 - 6.006 - 0.0066
        )

        fin_m, pos = recalculate_financial_metrics(
            trades=[buy_trade, sell_trade],
            current_price=Decimal("66000.00"),
            strategy_capital=Decimal("100.00"),
        )

        self.assertEqual(fin_m.closed_trades, 1)
        self.assertEqual(fin_m.winning_trades, 1)
        self.assertEqual(fin_m.win_rate_pct, 100.0)
        self.assertAlmostEqual(float(fin_m.realized_pnl), 0.59, places=2)
        self.assertGreater(fin_m.current_equity, Decimal("100.00"))
        self.assertEqual(pos.side, "NONE")

    def test_partial_fill_calculation(self) -> None:
        """Preenchimento parcial calcula com precisão preço médio de fill e custo."""
        partial_buy = TestnetTradeRecord(
            client_order_id="b_part_01",
            exchange_order_id="301",
            timestamp="2026-09-29T00:00:00Z",
            symbol="BTC/USDT",
            side="BUY",
            order_type="LIMIT",
            requested_quantity=Decimal("0.00020000"),
            executed_quantity=Decimal("0.00010000"),  # Metade preenchida
            limit_price=Decimal("60000.00"),
            average_fill_price=Decimal("60000.00"),
            notional=Decimal("6.00"),
            fee=Decimal("0.006"),
            fee_asset="USDT",
        )

        fin_m, pos = recalculate_financial_metrics(
            trades=[partial_buy],
            current_price=Decimal("65000.00"),
            strategy_capital=Decimal("100.00"),
        )

        self.assertEqual(pos.side, "LONG")
        self.assertEqual(pos.quantity, Decimal("0.00010000"))
        self.assertEqual(pos.entry_price, Decimal("60000.00"))
        # Valor de mercado 0.0001 * 65000 = 6.50. Custo = 6.006. Unrealized ~ 0.49
        self.assertGreater(fin_m.unrealized_pnl, Decimal("0.40"))
        self.assertGreater(fin_m.current_equity, Decimal("100.00"))

    # =========================================================================
    # 2. NORMALIZAÇÃO DE CAPITAL DA ESTRATÉGIA
    # =========================================================================

    def test_strategy_capital_normalization_independent_of_exchange_balance(self) -> None:
        """Capital normalizado (ex: 100 USDT) preserva integridade mesmo com milhões na exchange."""
        fake_adapter = FakeExchangeOrderAdapter(
            environment=BinanceEnvironment.SPOT_TESTNET,
            balances={
                "USDT": {"free": Decimal("5000000.00"), "used": Decimal("0"), "total": Decimal("5000000.00")},
                "BTC": {"free": Decimal("50.00"), "used": Decimal("0"), "total": Decimal("50.00")},
            },
        )
        cb = TestnetCircuitBreaker()
        candles = generate_candles([60000.0, 60100.0, 60200.0, 60300.0, 60400.0])

        res = execute_testnet_soak_cycle(
            config=self.cfg,
            storage=self.storage,
            order_storage=self.order_storage,
            adapter=fake_adapter,
            circuit_breaker=cb,
            credential_provider=self.fake_provider,
            candles_override=candles,
            ticker_override=60400.0,
        )

        self.assertEqual(res.financial_metrics.testnet_strategy_capital, Decimal("100.00"))
        self.assertEqual(res.financial_metrics.starting_equity, Decimal("100.00"))
        self.assertLess(res.financial_metrics.current_equity, Decimal("200.00"))

    # =========================================================================
    # 3. REINÍCIO SEGURO, CHECKPOINTS E DEDUPLICAÇÃO
    # =========================================================================

    def test_safe_restart_and_checkpoint_recovery(self) -> None:
        """Reinício do runner recupera total de ciclos, uptime e métricas."""
        cb = TestnetCircuitBreaker()
        candles = generate_candles([60000.0, 60100.0, 60200.0, 60300.0, 60400.0])
        fake_adapter = FakeExchangeOrderAdapter(environment=BinanceEnvironment.SPOT_TESTNET)

        res1 = execute_testnet_soak_cycle(
            config=self.cfg,
            storage=self.storage,
            order_storage=self.order_storage,
            adapter=fake_adapter,
            circuit_breaker=cb,
            credential_provider=self.fake_provider,
            candles_override=candles,
            ticker_override=60400.0,
        )
        self.assertEqual(res1.operational_metrics.total_cycles, 1)

        # Simula reinício instanciando novo circuit breaker a partir do estado salvo
        cb2 = TestnetCircuitBreaker.from_dict(self.storage.get_state("circuit_breaker", {}))
        res2 = execute_testnet_soak_cycle(
            config=self.cfg,
            storage=self.storage,
            order_storage=self.order_storage,
            adapter=fake_adapter,
            circuit_breaker=cb2,
            credential_provider=self.fake_provider,
            candles_override=candles,
            ticker_override=60400.0,
        )
        self.assertEqual(res2.operational_metrics.total_cycles, 2)
        self.assertEqual(res2.operational_metrics.duplicate_blocks, 1)

    def test_candle_deduplication_prevents_multiple_orders_on_same_candle(self) -> None:
        """Ciclos repetidos sobre o mesmo candle não geram ordem duplicada."""
        fake_adapter = FakeExchangeOrderAdapter(
            default_status=OrderStatus.FILLED,
            environment=BinanceEnvironment.SPOT_TESTNET,
        )
        cb = TestnetCircuitBreaker()
        # Candles em alta cruzando SMA curta > longa
        candles = generate_candles([50000.0, 50000.0, 50000.0, 48000.0, 60000.0])

        res1 = execute_testnet_soak_cycle(
            config=self.cfg,
            storage=self.storage,
            order_storage=self.order_storage,
            adapter=fake_adapter,
            circuit_breaker=cb,
            credential_provider=self.fake_provider,
            candles_override=candles,
            ticker_override=60000.0,
        )
        self.assertEqual(res1.cycle_status, "BUY_EXECUTED")
        self.assertEqual(len(fake_adapter.submitted_payloads), 1)

        # Repete ciclo com exatamente o mesmo candle
        res2 = execute_testnet_soak_cycle(
            config=self.cfg,
            storage=self.storage,
            order_storage=self.order_storage,
            adapter=fake_adapter,
            circuit_breaker=cb,
            credential_provider=self.fake_provider,
            candles_override=candles,
            ticker_override=60000.0,
        )
        # Nenhuma nova ordem submetida
        self.assertEqual(len(fake_adapter.submitted_payloads), 1)
        self.assertEqual(res2.operational_metrics.duplicate_blocks, 1)

    def test_reconcile_before_new_order_on_restart(self) -> None:
        """Ordem pendente em aberto no SQLite é reconciliada antes de qualquer novo ciclo."""
        self.order_storage.save_initial_order(
            correlation_id="corr_pend_01",
            client_order_id="finbot_pending_01",
            symbol="BTC/USDT",
            side="BUY",
            order_type="LIMIT",
            requested_quantity=Decimal("0.0001"),
            requested_notional=Decimal("6.00"),
            status=OrderStatus.SUBMITTED,
            created_at="2026-09-29T00:00:00Z",
        )

        fake_adapter = FakeExchangeOrderAdapter(environment=BinanceEnvironment.SPOT_TESTNET)
        # Registra ordem como preenchida na exchange
        fake_adapter.orders["finbot_pending_01"] = ExchangeOrderResult(
            client_order_id="finbot_pending_01",
            exchange_order_id="999",
            status=OrderStatus.FILLED,
            symbol="BTC/USDT",
            side="BUY",
            order_type="LIMIT",
            requested_quantity=Decimal("0.0001"),
            executed_quantity=Decimal("0.0001"),
            cumulative_quote_quantity=Decimal("6.00"),
            average_price=Decimal("60000.00"),
        )

        cb = TestnetCircuitBreaker()
        candles = generate_candles([60000.0, 60100.0, 60200.0, 60300.0, 60400.0])

        res = execute_testnet_soak_cycle(
            config=self.cfg,
            storage=self.storage,
            order_storage=self.order_storage,
            adapter=fake_adapter,
            circuit_breaker=cb,
            credential_provider=self.fake_provider,
            candles_override=candles,
            ticker_override=60400.0,
        )

        # Verifica se ordem pendente foi reconciliada
        reconciled = self.order_storage.get_order_by_client_order_id("finbot_pending_01")
        self.assertIsNotNone(reconciled)
        assert reconciled is not None
        self.assertEqual(reconciled["current_status"], "FILLED")
        self.assertGreater(res.operational_metrics.reconciliations, 0)

    # =========================================================================
    # 4. CIRCUIT BREAKERS E TRATAMENTO DE UNKNOWN
    # =========================================================================

    def test_unknown_order_trips_circuit_breaker(self) -> None:
        """Ordem em estado UNKNOWN dispara imediatamente o circuit breaker."""
        fake_adapter = FakeExchangeOrderAdapter(
            simulate_timeout=True,
            environment=BinanceEnvironment.SPOT_TESTNET,
        )
        cb = TestnetCircuitBreaker()
        candles = generate_candles([50000.0, 50000.0, 50000.0, 48000.0, 60000.0])

        res = execute_testnet_soak_cycle(
            config=self.cfg,
            storage=self.storage,
            order_storage=self.order_storage,
            adapter=fake_adapter,
            circuit_breaker=cb,
            credential_provider=self.fake_provider,
            candles_override=candles,
            ticker_override=60000.0,
        )

        self.assertTrue(cb.is_tripped)
        self.assertIn("UNKNOWN", cb.trip_reason)
        self.assertGreater(res.operational_metrics.unknown_orders, 0)

    def test_circuit_breaker_blocks_subsequent_orders(self) -> None:
        """Com circuit breaker disparado, novas ordens são categoricamente bloqueadas."""
        fake_adapter = FakeExchangeOrderAdapter(
            default_status=OrderStatus.FILLED,
            environment=BinanceEnvironment.SPOT_TESTNET,
        )
        cb = TestnetCircuitBreaker()
        cb.trip("Simulated critical failure")

        candles = generate_candles([50000.0, 50000.0, 50000.0, 48000.0, 60000.0], start_ts=1700000100000)

        res = execute_testnet_soak_cycle(
            config=self.cfg,
            storage=self.storage,
            order_storage=self.order_storage,
            adapter=fake_adapter,
            circuit_breaker=cb,
            credential_provider=self.fake_provider,
            candles_override=candles,
            ticker_override=60000.0,
        )

        self.assertEqual(res.cycle_status, "BLOCKED_CIRCUIT_BREAKER")
        self.assertEqual(len(fake_adapter.submitted_payloads), 0)

    def test_consecutive_errors_trip_circuit_breaker(self) -> None:
        """5 erros operacionais consecutivos disparam o disjuntor."""
        cb = TestnetCircuitBreaker()
        for i in range(4):
            cb.record_error("Temporary network error")
            self.assertFalse(cb.is_tripped)

        cb.record_error("5th consecutive error")
        self.assertTrue(cb.is_tripped)
        self.assertIn("Número excessivo de erros consecutivos", cb.trip_reason)

    # =========================================================================
    # 5. ISOLAMENTO DE PRODUÇÃO (INVIOLABILIDADE)
    # =========================================================================

    def test_production_environment_fails_closed(self) -> None:
        """Config com ambiente PRODUCTION é sumariamente bloqueada."""
        cfg_prod = Config(
            binance_environment=BinanceEnvironment.PRODUCTION,
            testnet_execution_enabled=True,
        )
        fake_adapter = FakeExchangeOrderAdapter(environment=BinanceEnvironment.SPOT_TESTNET)
        with self.assertRaises(TestnetSoakSentryError) as ctx:
            verify_testnet_soak_sentries(cfg_prod, fake_adapter, self.fake_provider)
        self.assertIn("SPOT_TESTNET", str(ctx.exception))

    def test_production_url_in_adapter_fails_closed(self) -> None:
        """Adapter apontando para api.binance.com é sumariamente bloqueado."""
        fake_adapter = FakeExchangeOrderAdapter(environment=BinanceEnvironment.SPOT_TESTNET)
        fake_adapter.urls = {
            "api": {
                "public": "https://api.binance.com/api/v3",
                "private": "https://api.binance.com/api/v3",
            }
        }
        with self.assertRaises(TestnetSoakSentryError) as ctx:
            verify_testnet_soak_sentries(self.cfg, fake_adapter, self.fake_provider)
        self.assertIn("api.binance.com", str(ctx.exception))

    def test_production_credentials_target_fails_closed(self) -> None:
        """Provedor com target de Produção é sumariamente bloqueado."""
        prod_prov = FakeCredentialProvider(target_name="FinBot/Binance/Production")
        fake_adapter = FakeExchangeOrderAdapter(environment=BinanceEnvironment.SPOT_TESTNET)
        with self.assertRaises(TestnetSoakSentryError) as ctx:
            verify_testnet_soak_sentries(self.cfg, fake_adapter, prod_prov)
        self.assertIn("Target de Produção detectado", str(ctx.exception))

    def test_real_order_submission_enabled_fails_closed(self) -> None:
        """real_order_submission_enabled == True bloqueia imediatamente o Soak."""
        cfg_live = Config(
            binance_environment=BinanceEnvironment.SPOT_TESTNET,
            testnet_execution_enabled=True,
            real_order_submission_enabled=True,
        )
        fake_adapter = FakeExchangeOrderAdapter(environment=BinanceEnvironment.SPOT_TESTNET)
        with self.assertRaises(TestnetSoakSentryError) as ctx:
            verify_testnet_soak_sentries(cfg_live, fake_adapter, self.fake_provider)
        self.assertIn("real_order_submission_enabled", str(ctx.exception))

    # =========================================================================
    # 6. COMANDOS READ-ONLY (PREVIEW E STATUS)
    # =========================================================================

    def test_read_only_preview_mode(self) -> None:
        """Preview opera em modo 100% read-only garantindo TESTNET_WRITE_EXECUTED = NO."""
        fake_adapter = FakeExchangeOrderAdapter(environment=BinanceEnvironment.SPOT_TESTNET)
        out = io.StringIO()
        with patch("sys.stdout", out):
            code = run_testnet_soak_preview(
                config=self.cfg,
                storage=self.storage,
                adapter=fake_adapter,
                credential_provider=self.fake_provider,
            )
        self.assertEqual(code, 0)
        output = out.getvalue()
        self.assertIn("TESTNET SOAK — DRY PREVIEW", output)
        self.assertIn("TESTNET_WRITE_EXECUTED         : NO", output)
        self.assertIn("PRODUCTION_WRITE_ENABLED       : NO", output)
        self.assertIn("PRODUCTION_ORDERS_SENT         : 0", output)

    def test_print_testnet_soak_status(self) -> None:
        """Relatório de status exibe métricas operacionais e financeiras sem expor segredos."""
        op_m = TestnetOperationalMetrics(
            uptime_seconds=3665.0,
            total_cycles=120,
            successful_cycles=119,
            orders_filled=2,
            unknown_orders=0,
            orphan_orders=0,
            api_errors=1,
        )
        fin_m = TestnetFinancialMetrics(
            testnet_strategy_capital=Decimal("100.00"),
            starting_equity=Decimal("100.00"),
            current_equity=Decimal("101.50"),
            realized_pnl=Decimal("1.50"),
            net_pnl=Decimal("1.50"),
            net_return_pct=1.5,
            max_drawdown_pct=0.2,
            win_rate_pct=100.0,
            profit_factor=999.99,
            total_trades=2,
            closed_trades=1,
        )
        self.storage.save_metrics_snapshot(op_m, fin_m)

        out = io.StringIO()
        with patch("sys.stdout", out):
            code = print_testnet_soak_status(storage=self.storage)
        self.assertEqual(code, 0)
        val = out.getvalue()
        self.assertIn("TESTNET_SOAK_STATUS", val)
        self.assertIn("UPTIME                         : 01h 01m 05s", val)
        self.assertIn("CURRENT_EQUITY                 : 101.50 USDT", val)
        self.assertIn("NET_PNL                        : 1.50 USDT", val)
        self.assertIn("PRODUCTION_WRITE_ENABLED       : NO", val)
        self.assertNotIn("test_key", val)
        self.assertNotIn("test_secret", val)


# =============================================================================
# 7. TESTES DA FASE 8.4C2E — HARDENING & DEPLOYMENT READINESS
# =============================================================================

class TestTestnetSoakHardening(unittest.TestCase):
    """Testes exaustivos das proteções de observabilidade, shutdown, restart, fees e slippage."""

    def setUp(self) -> None:
        self.storage = TestnetSoakStorage(":memory:")
        self.order_storage = LiveOrderStorage(":memory:")
        self.fake_provider = FakeCredentialProvider()
        self.cfg = Config(
            trading_mode="live",
            binance_environment=BinanceEnvironment.SPOT_TESTNET,
            testnet_execution_enabled=True,
            live_execution_enabled=False,
            real_order_submission_enabled=False,
            testnet_strategy_capital=100.0,
            testnet_soak_db_path=":memory:",
            short_window=2,
            long_window=4,
            paper_timeframe="1m",
        )

    # 1. STATUS REAL DO RUNNER & HEARTBEAT
    def test_runner_status_idle_before_execution(self) -> None:
        """Antes de qualquer ciclo ou inicialização, status é READY/IDLE."""
        status = determine_runner_status(self.storage)
        self.assertEqual(status, "READY/IDLE")

    def test_runner_status_running_with_fresh_heartbeat(self) -> None:
        """Durante execução ativa com heartbeat recente, status é RUNNING."""
        now = datetime.now(timezone.utc)
        self.storage.save_state("runner_status", "RUNNING")
        self.storage.save_state("last_heartbeat", now.isoformat())

        status = determine_runner_status(self.storage, heartbeat_timeout_seconds=180.0, now=now)
        self.assertEqual(status, "RUNNING")

    def test_runner_status_stopped_after_shutdown(self) -> None:
        """Após encerramento normal ou Ctrl+C, status é STOPPED."""
        self.storage.save_state("runner_status", "STOPPED")
        status = determine_runner_status(self.storage)
        self.assertEqual(status, "STOPPED")

    def test_runner_status_stale_heartbeat_shows_stopped(self) -> None:
        """Runner marcado como RUNNING mas com heartbeat expirado (>180s) deve reportar STOPPED."""
        now = datetime.now(timezone.utc)
        old_time = now - timedelta(seconds=300)
        self.storage.save_state("runner_status", "RUNNING")
        self.storage.save_state("last_heartbeat", old_time.isoformat())

        status = determine_runner_status(self.storage, heartbeat_timeout_seconds=180.0, now=now)
        self.assertEqual(status, "STOPPED")

    def test_runner_status_tripped_circuit_breaker(self) -> None:
        """Se o disjuntor de segurança estiver disparado, status é CIRCUIT_BREAKER_TRIPPED."""
        cb = TestnetCircuitBreaker()
        cb.trip("Falha crítica simulada")
        status = determine_runner_status(self.storage, circuit_breaker=cb)
        self.assertEqual(status, "CIRCUIT_BREAKER_TRIPPED")

    # 2. SHUTDOWN GRACIOSO
    def test_graceful_shutdown_persists_checkpoint_and_marks_stopped(self) -> None:
        """Shutdown gracioso persiste runner_status=STOPPED e timestamps de encerramento."""
        fake_adapter = FakeExchangeOrderAdapter(environment=BinanceEnvironment.SPOT_TESTNET)
        cb = TestnetCircuitBreaker()

        # Dispara execução com max_cycles=1 para testar encerramento normal e graceful
        with patch("finbot.testnet_soak.execute_testnet_soak_cycle") as mock_cycle:
            mock_cycle.return_value = TestnetSoakCycleResult(
                timestamp="2026-09-29T12:00:00Z",
                cycle_status="HOLD",
                signal=Signal.HOLD,
                closed_candle_time="12345",
                closed_candle_timestamp=12345,
                executed_order=None,
                circuit_breaker_tripped=False,
                circuit_breaker_reason="",
                operational_metrics=TestnetOperationalMetrics(uptime_seconds=1.0),
                financial_metrics=TestnetFinancialMetrics(testnet_strategy_capital=Decimal("100.00")),
                message="Mock cycle",
            )
            # Usa banco temporário em arquivo para verificar persistência pós-close
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as f:
                tmp_path = f.name

            try:
                tmp_storage = TestnetSoakStorage(tmp_path)
                code = run_testnet_soak_continuous(
                    config=self.cfg,
                    storage=tmp_storage,
                    order_storage=self.order_storage,
                    adapter=fake_adapter,
                    circuit_breaker=cb,
                    cycle_interval_seconds=0.01,
                    max_cycles=1,
                )
                self.assertEqual(code, 0)
                verify_storage = TestnetSoakStorage(tmp_path)
                self.assertEqual(verify_storage.get_state("runner_status"), "STOPPED")
                self.assertIsNotNone(verify_storage.get_state("shutdown_at"))
                verify_storage.close()
            finally:
                Path(tmp_path).unlink(missing_ok=True)

    # 3. RESTART SEGURO (RECONCILIAÇÃO ANTES DE QUALQUER ORDEM)
    def test_restart_reconciles_non_terminal_orders_before_strategy(self) -> None:
        """Restart detecta ordem SUBMITTED anterior e reconcilia com a exchange antes do ciclo."""
        cid = "pending_restart_001"
        self.order_storage.save_initial_order(
            correlation_id="corr_001",
            client_order_id=cid,
            symbol="BTC/USDT",
            side="BUY",
            order_type="MARKET",
            requested_quantity=Decimal("0.00010000"),
            requested_notional=Decimal("6.00"),
            status=OrderStatus.SUBMITTED,
            created_at="2026-09-29T10:00:00Z",
        )
        self.order_storage.update_order_status(
            client_order_id=cid,
            status=OrderStatus.SUBMITTED,
            updated_at="2026-09-29T10:00:00Z",
            exchange_order_id="ex_999",
        )

        fake_adapter = FakeExchangeOrderAdapter(environment=BinanceEnvironment.SPOT_TESTNET)
        fake_adapter.orders[cid] = ExchangeOrderResult(
            client_order_id=cid,
            exchange_order_id="ex_999",
            status=OrderStatus.FILLED,
            symbol="BTC/USDT",
            side="BUY",
            order_type="MARKET",
            requested_quantity=Decimal("0.00010000"),
            executed_quantity=Decimal("0.00010000"),
            cumulative_quote_quantity=Decimal("6.00"),
            average_price=Decimal("60000.00"),
            fee=Decimal("0.006"),
            fee_asset="USDT",
        )
        fake_adapter.orders["ex_999"] = fake_adapter.orders[cid]

        cb = TestnetCircuitBreaker()
        reconstructed_pos, can_proceed, _ = reconcile_pre_cycle_state(
            config=self.cfg,
            storage=self.storage,
            order_storage=self.order_storage,
            adapter=fake_adapter,
            circuit_breaker=cb,
        )

        self.assertTrue(can_proceed)
        self.assertFalse(cb.is_tripped)
        # Ordem foi reconciliada e trade foi gravado no banco de soak
        trades = self.storage.list_trades()
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].client_order_id, cid)
        self.assertEqual(reconstructed_pos.side, "LONG")
        self.assertEqual(reconstructed_pos.quantity, Decimal("0.00010000"))

    def test_restart_trips_circuit_breaker_on_unknown_order(self) -> None:
        """Restart com ordem pendente que não existe na exchange vira UNKNOWN e trava novos ciclos."""
        cid = "ghost_order_002"
        self.order_storage.save_initial_order(
            correlation_id="corr_002",
            client_order_id=cid,
            symbol="BTC/USDT",
            side="BUY",
            order_type="MARKET",
            requested_quantity=Decimal("0.00010000"),
            requested_notional=Decimal("6.00"),
            status=OrderStatus.SUBMITTED,
            created_at="2026-09-29T10:00:00Z",
        )
        self.order_storage.update_order_status(
            client_order_id=cid,
            status=OrderStatus.SUBMITTED,
            updated_at="2026-09-29T10:00:00Z",
            exchange_order_id="ex_ghost",
        )

        fake_adapter = FakeExchangeOrderAdapter(environment=BinanceEnvironment.SPOT_TESTNET)
        fake_adapter.orders.clear()
        cb = TestnetCircuitBreaker()

        _, can_proceed, _ = reconcile_pre_cycle_state(
            config=self.cfg,
            storage=self.storage,
            order_storage=self.order_storage,
            adapter=fake_adapter,
            circuit_breaker=cb,
        )

        self.assertFalse(can_proceed)
        self.assertTrue(cb.is_tripped)
        self.assertIn("UNKNOWN", cb.trip_reason)

    # 4. CONTABILIZAÇÃO DE FEES (EXCHANGE REPORTED VS ESTIMATED)
    def test_exchange_reported_fee_accounting(self) -> None:
        """Quando a exchange reporta fee real, ela é categorizada como EXCHANGE_REPORTED_FEES e descontada do Net PnL."""
        t_buy = TestnetTradeRecord(
            client_order_id="buy_01",
            exchange_order_id="ex_b1",
            timestamp="2026-09-29T10:00:00Z",
            symbol="BTC/USDT",
            side="BUY",
            order_type="MARKET",
            requested_quantity=Decimal("0.00010000"),
            executed_quantity=Decimal("0.00010000"),
            average_fill_price=Decimal("60000.00"),
            notional=Decimal("6.00"),
            fee=Decimal("0.05"),
            exchange_reported_fee=Decimal("0.05"),
            estimated_fee=Decimal("0.00"),
            fee_source="EXCHANGE",
        )
        t_sell = TestnetTradeRecord(
            client_order_id="sell_01",
            exchange_order_id="ex_s1",
            timestamp="2026-09-29T10:01:00Z",
            symbol="BTC/USDT",
            side="SELL",
            order_type="MARKET",
            requested_quantity=Decimal("0.00010000"),
            executed_quantity=Decimal("0.00010000"),
            average_fill_price=Decimal("65000.00"),
            notional=Decimal("6.50"),
            fee=Decimal("0.06"),
            exchange_reported_fee=Decimal("0.06"),
            estimated_fee=Decimal("0.00"),
            fee_source="EXCHANGE",
        )

        fin_m, pos = recalculate_financial_metrics(
            trades=[t_buy, t_sell],
            current_price=Decimal("65000.00"),
            strategy_capital=Decimal("100.00"),
        )

        # Gross PnL = (65000 - 60000) * 0.0001 = +0.50 USDT
        # Fees = 0.05 (BUY) + 0.06 (SELL) = 0.11 USDT
        # Net PnL = 0.50 - 0.11 = +0.39 USDT
        self.assertEqual(fin_m.exchange_reported_fees, Decimal("0.11"))
        self.assertEqual(fin_m.estimated_fees, Decimal("0.00"))
        self.assertEqual(fin_m.fees, Decimal("0.11"))
        self.assertEqual(fin_m.net_pnl, Decimal("0.39"))
        self.assertEqual(fin_m.current_equity, Decimal("100.39"))

    def test_estimated_fee_fallback_accounting(self) -> None:
        """Quando a exchange reporta 0 ou None, taxa estimada (0.10%) é usada e categorizada como ESTIMATED_FEES."""
        t_buy = TestnetTradeRecord(
            client_order_id="buy_02",
            exchange_order_id="ex_b2",
            timestamp="2026-09-29T10:00:00Z",
            symbol="BTC/USDT",
            side="BUY",
            order_type="MARKET",
            requested_quantity=Decimal("0.00010000"),
            executed_quantity=Decimal("0.00010000"),
            average_fill_price=Decimal("60000.00"),
            notional=Decimal("6.00"),
            fee=Decimal("0.006"),
            exchange_reported_fee=Decimal("0.00"),
            estimated_fee=Decimal("0.006"),
            fee_source="ESTIMATED",
        )
        t_sell = TestnetTradeRecord(
            client_order_id="sell_02",
            exchange_order_id="ex_s2",
            timestamp="2026-09-29T10:01:00Z",
            symbol="BTC/USDT",
            side="SELL",
            order_type="MARKET",
            requested_quantity=Decimal("0.00010000"),
            executed_quantity=Decimal("0.00010000"),
            average_fill_price=Decimal("65000.00"),
            notional=Decimal("6.50"),
            fee=Decimal("0.0065"),
            exchange_reported_fee=Decimal("0.00"),
            estimated_fee=Decimal("0.0065"),
            fee_source="ESTIMATED",
        )

        fin_m, pos = recalculate_financial_metrics(
            trades=[t_buy, t_sell],
            current_price=Decimal("65000.00"),
            strategy_capital=Decimal("100.00"),
        )

        self.assertEqual(fin_m.exchange_reported_fees, Decimal("0.00"))
        self.assertEqual(fin_m.estimated_fees, Decimal("0.01"))  # quantizado a 2 casas = 0.01
        self.assertEqual(fin_m.fees, Decimal("0.01"))
        # Gross = 0.50, effective fees = 0.0125 -> Net PnL = 0.4875 -> 0.49
        self.assertEqual(fin_m.net_pnl, Decimal("0.49"))

    # 5. ESTIMATIVA DE SLIPPAGE (BUY & SELL SEM DUPLA CONTAGEM)
    def test_slippage_calculation_buy_and_sell(self) -> None:
        """Slippage é calculado por fill: BUY = (fill - ref), SELL = (ref - fill), sem dupla dedução no Net PnL."""
        # BUY com slippage adverso (+60 USDT, +10 bps)
        t_buy = TestnetTradeRecord(
            client_order_id="buy_slip",
            exchange_order_id="ex_bs",
            timestamp="2026-09-29T10:00:00Z",
            symbol="BTC/USDT",
            side="BUY",
            order_type="MARKET",
            requested_quantity=Decimal("0.00010000"),
            executed_quantity=Decimal("0.00010000"),
            average_fill_price=Decimal("60060.00"),
            reference_price=Decimal("60000.00"),
            estimated_slippage_usdt=Decimal("0.0060"),
            estimated_slippage_bps=Decimal("10.00"),
            notional=Decimal("6.006"),
            fee=Decimal("0.00"),
        )
        # SELL com slippage adverso (-65 USDT, +10 bps)
        t_sell = TestnetTradeRecord(
            client_order_id="sell_slip",
            exchange_order_id="ex_ss",
            timestamp="2026-09-29T10:01:00Z",
            symbol="BTC/USDT",
            side="SELL",
            order_type="MARKET",
            requested_quantity=Decimal("0.00010000"),
            executed_quantity=Decimal("0.00010000"),
            average_fill_price=Decimal("64935.00"),
            reference_price=Decimal("65000.00"),
            estimated_slippage_usdt=Decimal("0.0065"),
            estimated_slippage_bps=Decimal("10.00"),
            notional=Decimal("6.4935"),
            fee=Decimal("0.00"),
        )

        fin_m, _ = recalculate_financial_metrics(
            trades=[t_buy, t_sell],
            current_price=Decimal("64935.00"),
            strategy_capital=Decimal("100.00"),
        )

        # Slippage total = 0.0060 + 0.0065 = 0.0125 -> quantizado para 0.01 USDT
        self.assertEqual(fin_m.estimated_slippage, Decimal("0.01"))
        self.assertEqual(fin_m.estimated_slippage_bps, Decimal("10.00"))

        # Inviolabilidade contra dupla contagem:
        # Cash out = 6.0060, Cash in = 6.4935
        # Net PnL = 6.4935 - 6.0060 = +0.4875 -> 0.49 USDT (fill real já determinou o fluxo!)
        self.assertEqual(fin_m.net_pnl, Decimal("0.49"))

    # 6. MÉTRICAS DERIVADAS & TRADES PARCIAIS
    def test_partial_fill_and_derived_metrics(self) -> None:
        """Preenchimento parcial rateia custo e calcula win rate, profit factor e expectancy corretamente."""
        # BUY 0.0002 BTC @ 60000 USDT (custo = 12.00 USDT)
        t_buy = TestnetTradeRecord(
            client_order_id="buy_p1",
            exchange_order_id="ex_bp1",
            timestamp="2026-09-29T10:00:00Z",
            symbol="BTC/USDT",
            side="BUY",
            order_type="MARKET",
            requested_quantity=Decimal("0.00020000"),
            executed_quantity=Decimal("0.00020000"),
            average_fill_price=Decimal("60000.00"),
            notional=Decimal("12.00"),
            fee=Decimal("0.00"),
        )
        # SELL parcial de 0.0001 BTC @ 70000 USDT (receita = 7.00 USDT, custo = 6.00 USDT, lucro = 1.00 USDT)
        t_sell_part = TestnetTradeRecord(
            client_order_id="sell_p1",
            exchange_order_id="ex_sp1",
            timestamp="2026-09-29T10:01:00Z",
            symbol="BTC/USDT",
            side="SELL",
            order_type="MARKET",
            requested_quantity=Decimal("0.00010000"),
            executed_quantity=Decimal("0.00010000"),
            average_fill_price=Decimal("70000.00"),
            notional=Decimal("7.00"),
            fee=Decimal("0.00"),
        )

        fin_m, pos = recalculate_financial_metrics(
            trades=[t_buy, t_sell_part],
            current_price=Decimal("70000.00"),
            strategy_capital=Decimal("100.00"),
        )

        self.assertEqual(fin_m.closed_trades, 1)
        self.assertEqual(fin_m.realized_pnl, Decimal("1.00"))
        # Posição restante: 0.0001 BTC
        self.assertEqual(pos.side, "LONG")
        self.assertEqual(pos.quantity, Decimal("0.00010000"))
        # Unrealized PnL da posição restante @ 70000 vs custo 6.00 = +1.00 USDT
        self.assertEqual(fin_m.unrealized_pnl, Decimal("1.00"))
        self.assertEqual(fin_m.net_pnl, Decimal("2.00"))
        self.assertEqual(fin_m.win_rate_pct, 100.0)
        self.assertEqual(fin_m.profit_factor, 999.99)
        self.assertEqual(fin_m.average_win, Decimal("1.00"))
        self.assertIsNone(fin_m.average_loss)


if __name__ == "__main__":
    unittest.main()
