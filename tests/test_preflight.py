"""Testes unitários e de segurança para o módulo de Pre-Flight (FASE 8.4C1A).

Garante que o comando python -m finbot.preflight:
1. Valida a presença de credenciais sem expô-las
2. Valida autenticação privada e leitura de saldos sem expor valores patrimoniais
3. Carrega e valida metadados de mercado e filtros do CCXT
4. Calcula a micro-ordem candidata dentro do teto e acima do mínimo
5. Verifica fundos disponíveis passivamente
6. Executa o pipeline de segurança simulado em modo DRY_RUN
7. Valida a barreira final (real_order_submission_enabled == False)
8. Valida as barreiras de create_order e cancel_order (LiveTradingBlockedError)
9. Assegura ZERO chamadas de ordem para a rede e ZERO ordens reais enviadas
"""

from decimal import Decimal
import io
import unittest
from unittest.mock import MagicMock, patch

from finbot.config import Config
from finbot.credentials import BinanceCredentials, FakeCredentialProvider
from finbot.exchange import TickerData
from finbot.live_safety import (
    MarketFilters,
)
from finbot.preflight import (
    PreflightResult,
    calculate_micro_order_candidate,
    format_preflight_report,
    main,
    run_preflight,
)
from finbot.private_exchange import (
    AccountStatus,
    AuthenticationError,
    BalanceData,
    BinancePrivateExchange,
    LiveTradingBlockedError,
)


class TestPreflight(unittest.TestCase):
    """Bateria de testes unitários herméticos para o comando de Pre-Flight."""

    def setUp(self) -> None:
        self.config = Config(
            trading_mode="paper",
            live_trading_acknowledged=False,
            live_execution_enabled=False,
            live_micro_order_max_notional=15.0,
            real_order_submission_enabled=False,
        )
        self.market_data = {
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
            "info": {
                "filters": [
                    {"filterType": "LOT_SIZE", "minQty": "0.00001", "maxQty": "9000.0", "stepSize": "0.00001"},
                    {"filterType": "PRICE_FILTER", "minPrice": "0.01", "maxPrice": "1000000.0", "tickSize": "0.01"},
                    {"filterType": "NOTIONAL", "minNotional": "5.0"},
                ]
            },
        }

        self.mock_pub_exchange = MagicMock()
        self.mock_pub_exchange.load_markets.return_value = {"BTC/USDT": self.market_data}
        self.mock_pub_exchange.market.return_value = self.market_data

        # Mock ticker helper
        self.ticker = TickerData(
            symbol="BTC/USDT",
            last=60000.0,
            bid=59999.0,
            ask=60001.0,
            timestamp=1700000000000,
            datetime="2026-09-28 12:00:00",
        )

        self.mock_priv_exchange = MagicMock(spec=BinancePrivateExchange)
        self.mock_priv_exchange.get_account_status.return_value = AccountStatus(
            account_type="SPOT",
            can_trade=True,
            can_withdraw=False,
            can_deposit=False,
        )
        self.mock_priv_exchange.get_balances.return_value = {
            "USDT": BalanceData(asset="USDT", free=Decimal("50.00"), locked=Decimal("0.0"), total=Decimal("50.00")),
            "BTC": BalanceData(asset="BTC", free=Decimal("0.001"), locked=Decimal("0.0"), total=Decimal("0.001")),
        }
        self.mock_priv_exchange.create_order.side_effect = LiveTradingBlockedError("create_order blocked")
        self.mock_priv_exchange.cancel_order.side_effect = LiveTradingBlockedError("cancel_order blocked")

        self.cred_provider = FakeCredentialProvider(
            api_key="mock_key_12345678", api_secret="mock_secret_12345678"
        )

    @patch("finbot.preflight.fetch_ticker")
    def test_preflight_all_checks_pass(self, mock_fetch_ticker: MagicMock) -> None:
        """Cenário ideal: todas as verificações passam e o readiness reporta YES."""
        mock_fetch_ticker.return_value = self.ticker

        res = run_preflight(
            config=self.config,
            credential_provider=self.cred_provider,
            private_exchange=self.mock_priv_exchange,
            public_exchange=self.mock_pub_exchange,
        )

        self.assertTrue(res.credentials_present)
        self.assertTrue(res.binance_private_auth_pass)
        self.assertTrue(res.private_balance_read_pass)
        self.assertTrue(res.market_filter_guard_pass)
        self.assertTrue(res.safe_micro_order_possible)
        self.assertTrue(res.funds_available_for_candidate)
        self.assertEqual(res.dry_run_status, "SIMULATED_ACCEPTED")
        self.assertTrue(res.final_live_barrier_pass)
        self.assertTrue(res.create_order_barrier_pass)
        self.assertTrue(res.cancel_order_barrier_pass)
        self.assertEqual(res.real_orders_sent, 0)
        self.assertEqual(res.order_network_calls, 0)
        self.assertTrue(res.ready_for_8_4c2)

        report = format_preflight_report(res)
        self.assertIn("READY_FOR_8_4C2 = YES", report)
        self.assertIn("DRY_RUN = SIMULATED_ACCEPTED", report)
        self.assertIn("SAFE_MICRO_ORDER_POSSIBLE = YES", report)
        self.assertIn("FUNDS_AVAILABLE_FOR_CANDIDATE = YES", report)
        self.assertIn("FINAL_LIVE_BARRIER = PASS", report)

    @patch("finbot.preflight.fetch_ticker")
    def test_preflight_credentials_missing(self, mock_fetch_ticker: MagicMock) -> None:
        """Quando não há credenciais, falha autenticação e readiness fica NO."""
        mock_fetch_ticker.return_value = self.ticker
        empty_provider = FakeCredentialProvider(api_key=None, api_secret=None)

        res = run_preflight(
            config=self.config,
            credential_provider=empty_provider,
            private_exchange=None,
            public_exchange=self.mock_pub_exchange,
        )

        self.assertFalse(res.credentials_present)
        self.assertFalse(res.binance_private_auth_pass)
        self.assertFalse(res.private_balance_read_pass)
        self.assertFalse(res.funds_available_for_candidate)
        self.assertFalse(res.ready_for_8_4c2)

        report = format_preflight_report(res)
        self.assertIn("CREDENTIALS = MISSING", report)
        self.assertIn("READY_FOR_8_4C2 = NO", report)

    @patch("finbot.preflight.fetch_ticker")
    def test_preflight_auth_failure(self, mock_fetch_ticker: MagicMock) -> None:
        """Quando a chamada de status falha com erro de autenticação."""
        mock_fetch_ticker.return_value = self.ticker
        self.mock_priv_exchange.get_account_status.side_effect = AuthenticationError("Signature invalid")

        res = run_preflight(
            config=self.config,
            credential_provider=self.cred_provider,
            private_exchange=self.mock_priv_exchange,
            public_exchange=self.mock_pub_exchange,
        )

        self.assertFalse(res.binance_private_auth_pass)
        self.assertFalse(res.ready_for_8_4c2)

        report = format_preflight_report(res)
        self.assertIn("BINANCE_PRIVATE_AUTH = FAIL", report)
        self.assertIn("READY_FOR_8_4C2 = NO", report)

    @patch("finbot.preflight.fetch_ticker")
    def test_preflight_metadata_failure(self, mock_fetch_ticker: MagicMock) -> None:
        """Quando o CCXT público falha ao carregar mercados."""
        mock_fetch_ticker.return_value = None
        self.mock_pub_exchange.load_markets.side_effect = Exception("Public network timeout")

        res = run_preflight(
            config=self.config,
            credential_provider=self.cred_provider,
            private_exchange=self.mock_priv_exchange,
            public_exchange=self.mock_pub_exchange,
        )

        self.assertFalse(res.market_filter_guard_pass)
        self.assertFalse(res.safe_micro_order_possible)
        self.assertFalse(res.ready_for_8_4c2)

        report = format_preflight_report(res)
        self.assertIn("MARKET_FILTER_GUARD = FAIL", report)
        self.assertIn("READY_FOR_8_4C2 = NO", report)

    @patch("finbot.preflight.fetch_ticker")
    def test_preflight_invalid_market_filters(self, mock_fetch_ticker: MagicMock) -> None:
        """Filtros corrompidos com step_size <= 0 devem falhar no guard."""
        mock_fetch_ticker.return_value = self.ticker
        corrupted_data = dict(self.market_data)
        corrupted_data["limits"] = {"amount": {"min": 0, "max": 0}, "cost": {"min": 0}}
        corrupted_data["precision"] = {"amount": 0, "price": 0}
        corrupted_data["info"] = {"filters": []}
        self.mock_pub_exchange.market.return_value = corrupted_data

        res = run_preflight(
            config=self.config,
            credential_provider=self.cred_provider,
            private_exchange=self.mock_priv_exchange,
            public_exchange=self.mock_pub_exchange,
        )

        self.assertFalse(res.market_filter_guard_pass)
        self.assertFalse(res.safe_micro_order_possible)
        self.assertFalse(res.ready_for_8_4c2)

    @patch("finbot.preflight.fetch_ticker")
    def test_preflight_candidate_impossible_high_min_cost(self, mock_fetch_ticker: MagicMock) -> None:
        """Se minNotional da exchange for superior ao live_micro_order_max_notional, rejeita."""
        mock_fetch_ticker.return_value = self.ticker
        high_cost_data = dict(self.market_data)
        high_cost_data["limits"] = {
            "amount": {"min": 0.00001},
            "price": {"min": 0.01},
            "cost": {"min": 25.0},
        }
        high_cost_data["info"] = {
            "filters": [
                {"filterType": "NOTIONAL", "minNotional": "25.0"},
            ]
        }
        self.mock_pub_exchange.market.return_value = high_cost_data

        res = run_preflight(
            config=self.config,  # micro_order_cap = 15.0
            credential_provider=self.cred_provider,
            private_exchange=self.mock_priv_exchange,
            public_exchange=self.mock_pub_exchange,
        )

        self.assertTrue(res.market_filter_guard_pass)
        self.assertFalse(res.safe_micro_order_possible)
        self.assertFalse(res.ready_for_8_4c2)

        report = format_preflight_report(res)
        self.assertIn("SAFE_MICRO_ORDER_POSSIBLE = NO", report)
        self.assertIn("READY_FOR_8_4C2 = NO", report)

    @patch("finbot.preflight.fetch_ticker")
    def test_preflight_insufficient_funds(self, mock_fetch_ticker: MagicMock) -> None:
        """Quando o saldo em USDT é inferior ao notional da candidata (e.g. 6.00 USDT)."""
        mock_fetch_ticker.return_value = self.ticker
        self.mock_priv_exchange.get_balances.return_value = {
            "USDT": BalanceData(asset="USDT", free=Decimal("2.00"), locked=Decimal("0.0"), total=Decimal("2.00")),
            "BTC": BalanceData(asset="BTC", free=Decimal("0.0"), locked=Decimal("0.0"), total=Decimal("0.0")),
        }

        res = run_preflight(
            config=self.config,
            credential_provider=self.cred_provider,
            private_exchange=self.mock_priv_exchange,
            public_exchange=self.mock_pub_exchange,
        )

        self.assertTrue(res.safe_micro_order_possible)
        self.assertFalse(res.funds_available_for_candidate)
        self.assertNotEqual(res.dry_run_status, "SIMULATED_ACCEPTED")
        self.assertFalse(res.ready_for_8_4c2)

        report = format_preflight_report(res)
        self.assertIn("FUNDS_AVAILABLE_FOR_CANDIDATE = NO", report)
        self.assertIn("READY_FOR_8_4C2 = NO", report)

    @patch("finbot.preflight.fetch_ticker")
    def test_preflight_final_live_barrier_failure(self, mock_fetch_ticker: MagicMock) -> None:
        """Se por anomalia real_order_submission_enabled estiver True, a barreira final falha."""
        mock_fetch_ticker.return_value = self.ticker
        leaked_config = Config(
            trading_mode="live",
            real_order_submission_enabled=True,
            live_micro_order_max_notional=15.0,
        )

        res = run_preflight(
            config=leaked_config,
            credential_provider=self.cred_provider,
            private_exchange=self.mock_priv_exchange,
            public_exchange=self.mock_pub_exchange,
        )

        self.assertFalse(res.final_live_barrier_pass)
        self.assertFalse(res.ready_for_8_4c2)

        report = format_preflight_report(res)
        self.assertIn("FINAL_LIVE_BARRIER = FAIL", report)
        self.assertIn("READY_FOR_8_4C2 = NO", report)

    @patch("finbot.preflight.fetch_ticker")
    def test_preflight_no_credentials_in_output(self, mock_fetch_ticker: MagicMock) -> None:
        """Garante que nem a API Key nem o Secret aparecem no relatório de saída."""
        mock_fetch_ticker.return_value = self.ticker
        secret_key = "super_secret_binance_key_999"
        secret_hash = "super_secret_binance_hash_888"

        cred_provider = FakeCredentialProvider(
            api_key=secret_key, api_secret=secret_hash
        )

        res = run_preflight(
            config=self.config,
            credential_provider=cred_provider,
            private_exchange=self.mock_priv_exchange,
            public_exchange=self.mock_pub_exchange,
        )

        report = format_preflight_report(res)
        self.assertNotIn(secret_key, report)
        self.assertNotIn(secret_hash, report)
        self.assertNotIn("mock_key", report)
        self.assertNotIn("mock_secret", report)

    @patch("finbot.preflight.fetch_ticker")
    def test_preflight_no_balances_in_output(self, mock_fetch_ticker: MagicMock) -> None:
        """Garante que nenhum saldo patrimonial real seja impresso no relatório."""
        mock_fetch_ticker.return_value = self.ticker
        special_balance = Decimal("12345.67")
        self.mock_priv_exchange.get_balances.return_value = {
            "USDT": BalanceData(asset="USDT", free=special_balance, locked=Decimal("0.0"), total=special_balance),
        }

        res = run_preflight(
            config=self.config,
            credential_provider=self.cred_provider,
            private_exchange=self.mock_priv_exchange,
            public_exchange=self.mock_pub_exchange,
        )

        report = format_preflight_report(res)
        self.assertNotIn("12345.67", report)
        self.assertNotIn("12345", report)

    @patch("finbot.preflight.fetch_ticker")
    def test_preflight_cannot_submit_or_cancel_real_orders(self, mock_fetch_ticker: MagicMock) -> None:
        """SENTINELA: Garante que durante todo o preflight, create_order e cancel_order NUNCA são chamados."""
        mock_fetch_ticker.return_value = self.ticker

        res = run_preflight(
            config=self.config,
            credential_provider=self.cred_provider,
            private_exchange=self.mock_priv_exchange,
            public_exchange=self.mock_pub_exchange,
        )

        # O teste de barreira chama create_order e cancel_order mas eles levantam LiveTradingBlockedError
        # e nenhuma requisição de rede de envio de ordem ocorre
        self.assertEqual(res.real_orders_sent, 0)
        self.assertEqual(res.order_network_calls, 0)

        # Verificação do relatório
        report = format_preflight_report(res)
        self.assertIn("REAL_ORDERS_SENT = 0", report)
        self.assertIn("ORDER_NETWORK_CALLS = 0", report)

    def test_calculate_micro_order_candidate_math(self) -> None:
        """Validação matemática detalhada de calculate_micro_order_candidate."""
        filters = MarketFilters(
            symbol="BTC/USDT",
            base_asset="BTC",
            quote_asset="USDT",
            min_amount=Decimal("0.00001"),
            max_amount=Decimal("9000.0"),
            amount_step=Decimal("0.00001"),
            min_price=Decimal("0.01"),
            max_price=Decimal("1000000.0"),
            price_step=Decimal("0.01"),
            min_cost=Decimal("5.0"),
            max_cost=None,
        )

        # 1. Preço BTC = $60,000.00, teto = $15.00
        cand = calculate_micro_order_candidate(filters, Decimal("60000.00"), Decimal("15.00"))
        self.assertIsNotNone(cand)
        qty, px, notional = cand
        self.assertEqual(px, Decimal("60000.00"))
        self.assertGreater(notional, Decimal("5.0"))
        self.assertLessEqual(notional, Decimal("15.0"))
        self.assertGreaterEqual(qty, Decimal("0.00001"))
        self.assertEqual(qty % Decimal("0.00001"), Decimal("0"))

        # 2. Preço BTC = $100,000.00
        cand2 = calculate_micro_order_candidate(filters, Decimal("100000.00"), Decimal("15.00"))
        self.assertIsNotNone(cand2)
        qty2, px2, notional2 = cand2
        self.assertGreater(notional2, Decimal("5.0"))
        self.assertLessEqual(notional2, Decimal("15.0"))

        # 3. Teto inferior ao min_cost -> impossível
        cand_low_cap = calculate_micro_order_candidate(filters, Decimal("60000.00"), Decimal("4.00"))
        self.assertIsNone(cand_low_cap)

        # 4. Preço inválido <= 0
        self.assertIsNone(calculate_micro_order_candidate(filters, Decimal("0"), Decimal("15.00")))
        self.assertIsNone(calculate_micro_order_candidate(filters, Decimal("-100"), Decimal("15.00")))

    @patch("finbot.preflight.run_preflight")
    def test_main_cli_returns_zero_on_ready(self, mock_run: MagicMock) -> None:
        """CLI main() retorna 0 quando ready_for_8_4c2 é True."""
        mock_res = PreflightResult()
        mock_res.ready_for_8_4c2 = True
        mock_run.return_value = mock_res

        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            code = main()
            self.assertEqual(code, 0)
            self.assertIn("READY_FOR_8_4C2 = YES", mock_out.getvalue())

    @patch("finbot.preflight.run_preflight")
    def test_main_cli_returns_one_on_not_ready(self, mock_run: MagicMock) -> None:
        """CLI main() retorna 1 quando ready_for_8_4c2 é False."""
        mock_res = PreflightResult()
        mock_res.ready_for_8_4c2 = False
        mock_run.return_value = mock_res

        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            code = main()
            self.assertEqual(code, 1)
            self.assertIn("READY_FOR_8_4C2 = NO", mock_out.getvalue())


if __name__ == "__main__":
    unittest.main()
