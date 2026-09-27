"""Suíte de testes para a FASE 8.1 — Binance Private Integration Foundation.

Valida todos os requisitos de segurança, isolamento, sanitização de segredos,
comportamento fail-closed e proibição estrita de ordens reais.
"""

from __future__ import annotations

from decimal import Decimal
import logging
import unittest
from unittest.mock import MagicMock, patch

import ccxt

from finbot.config import Config, get_config
from finbot.private_exchange import (
    AccountSnapshot,
    AccountStatus,
    AuthenticationError,
    BalanceData,
    BinancePrivateExchange,
    CredentialsMissingError,
    InvalidConfigurationError,
    LiveTradingBlockedError,
    NetworkError,
    PrivateExchangeError,
    RateLimitError,
    sanitize_secret_text,
)


class TestPrivateExchangeConfigAndSecurity(unittest.TestCase):
    """Testes de configuração, fronteira Paper/Live e segurança de segredos."""

    def test_default_trading_mode_is_paper(self) -> None:
        """1. Modo de trading padrão da aplicação é estritamente 'paper'."""
        cfg = Config()
        self.assertEqual(cfg.trading_mode, "paper")

        cfg_from_fn = get_config()
        self.assertEqual(cfg_from_fn.trading_mode, "paper")

    def test_invalid_trading_mode_defaults_safely_to_paper(self) -> None:
        """2. Qualquer valor inválido para trading_mode é sanitizado para 'paper'."""
        invalid_modes = ["disabled", "sandbox", "real", "LIVE_NOW", "unknown", "", None]
        for mode in invalid_modes:
            with self.subTest(mode=mode):
                cfg = Config(trading_mode=mode)  # type: ignore[arg-type]
                self.assertEqual(cfg.trading_mode, "paper")

    def test_paper_mode_blocks_private_exchange_instantiation(self) -> None:
        """3. O modo paper impede categoricamente a instanciação do cliente privado."""
        cfg_paper = Config(
            trading_mode="paper",
            binance_api_key="dummy_key_12345",
            binance_api_secret="dummy_secret_67890",
        )
        with self.assertRaises(InvalidConfigurationError) as ctx:
            BinancePrivateExchange(cfg_paper)
        self.assertIn("paper", str(ctx.exception))

    def test_missing_credentials_fails_closed(self) -> None:
        """4. Ausência de API key ou Secret levanta CredentialsMissingError (Fail-Closed)."""
        scenarios = [
            ("", ""),
            ("my_key", ""),
            ("", "my_secret"),
            ("   ", "   "),
        ]
        for key, secret in scenarios:
            with self.subTest(key=key, secret=secret):
                cfg_live = Config(
                    trading_mode="live",
                    binance_api_key=key,
                    binance_api_secret=secret,
                )
                with self.assertRaises(CredentialsMissingError):
                    BinancePrivateExchange(cfg_live)

    def test_secrets_never_appear_in_config_repr_or_str(self) -> None:
        """5. Chave e segredo da API NUNCA aparecem em repr(config) ou str(config)."""
        secret_sample = "TOP_SECRET_API_KEY_999"
        key_sample = "PUBLIC_KEY_SAMPLE_111"

        cfg = Config(
            trading_mode="live",
            binance_api_key=key_sample,
            binance_api_secret=secret_sample,
        )
        repr_str = repr(cfg)
        str_str = str(cfg)

        self.assertNotIn(secret_sample, repr_str)
        self.assertNotIn(key_sample, repr_str)
        self.assertNotIn(secret_sample, str_str)
        self.assertNotIn(key_sample, str_str)

    def test_secrets_never_appear_in_client_repr_or_str(self) -> None:
        """6. Chave e segredo da API NUNCA aparecem em repr(client) ou str(client)."""
        secret_sample = "MY_VERY_SECRET_KEY_XYZ"
        key_sample = "MY_PUBLIC_API_KEY_ABC"

        cfg = Config(
            trading_mode="live",
            binance_api_key=key_sample,
            binance_api_secret=secret_sample,
        )
        mock_ccxt = MagicMock()
        client = BinancePrivateExchange(cfg, client=mock_ccxt)

        self.assertNotIn(secret_sample, repr(client))
        self.assertNotIn(key_sample, repr(client))
        self.assertNotIn(secret_sample, str(client))
        self.assertNotIn(key_sample, str(client))

    def test_sanitizer_replaces_secrets(self) -> None:
        """7. Sanitizador substitui chaves por [REDACTED]."""
        secret = "ultra_sensitive_secret_value"
        raw_msg = f"Error connecting with key {secret} on endpoint /account"
        sanitized = sanitize_secret_text(raw_msg, [secret])
        self.assertNotIn(secret, sanitized)
        self.assertIn("[REDACTED]", sanitized)

    def test_secrets_never_leak_into_logs_on_error(self) -> None:
        """8. Mensagens de erro de exceções da exchange não vazam chaves nos logs."""
        secret = "SUPER_SECRET_SIGNATURE_KEY_12345"
        key = "SUPER_API_KEY_ABCD_54321"

        cfg = Config(
            trading_mode="live",
            binance_api_key=key,
            binance_api_secret=secret,
        )
        mock_ccxt = MagicMock()
        mock_ccxt.fetch_balance.side_effect = ccxt.AuthenticationError(
            f"Invalid API-key, IP, or permissions for action, request was signed with {secret}"
        )

        client = BinancePrivateExchange(cfg, client=mock_ccxt)

        with self.assertLogs("finbot.private_exchange", level="ERROR") as cm:
            with self.assertRaises(AuthenticationError) as ctx:
                client.get_account_status()

            # Verifica que o segredo foi mascarado tanto na exceção quanto nos logs
            self.assertNotIn(secret, str(ctx.exception))
            self.assertIn("[REDACTED]", str(ctx.exception))
            for log_msg in cm.output:
                self.assertNotIn(secret, log_msg)
                self.assertNotIn(key, log_msg)


class TestPrivateExchangeResponses(unittest.TestCase):
    """Testes com mock do CCXT para respostas válidas e tratadas da Binance."""

    def setUp(self) -> None:
        self.cfg = Config(
            trading_mode="live",
            binance_api_key="dummy_api_key_live",
            binance_api_secret="dummy_api_secret_live",
        )
        self.mock_ccxt = MagicMock()
        self.client = BinancePrivateExchange(self.cfg, client=self.mock_ccxt)

    def test_get_account_status_spot(self) -> None:
        """9. Consulta e normalização correta do status da conta Spot."""
        self.mock_ccxt.fetch_balance.return_value = {
            "info": {
                "accountType": "SPOT",
                "canTrade": True,
                "canWithdraw": False,
                "canDeposit": True,
                "buyerCommission": 0,
                "sellerCommission": 0,
                "updateTime": 1700000000000,
            }
        }

        status = self.client.get_account_status()
        self.assertIsInstance(status, AccountStatus)
        self.assertEqual(status.account_type, "SPOT")
        self.assertTrue(status.can_trade)
        self.assertFalse(status.can_withdraw)
        self.assertTrue(status.can_deposit)
        self.assertEqual(status.update_time, 1700000000000)

    def test_get_balances_filtering_zeros(self) -> None:
        """10. Consulta de saldos com conversão Decimal e filtro de saldos zerados."""
        self.mock_ccxt.fetch_balance.return_value = {
            "info": {},
            "free": {"BTC": 0.05, "USDT": 500.0, "ETH": 0.0},
            "used": {"BTC": 0.01, "USDT": 0.0, "ETH": 0.0},
            "total": {"BTC": 0.06, "USDT": 500.0, "ETH": 0.0},
        }

        # Com non_zero_only=True (padrão)
        balances = self.client.get_balances(non_zero_only=True)
        self.assertIn("BTC", balances)
        self.assertIn("USDT", balances)
        self.assertNotIn("ETH", balances)

        btc_bal = balances["BTC"]
        self.assertEqual(btc_bal.free, Decimal("0.05"))
        self.assertEqual(btc_bal.locked, Decimal("0.01"))
        self.assertEqual(btc_bal.total, Decimal("0.06"))

        # Com non_zero_only=False
        all_balances = self.client.get_balances(non_zero_only=False)
        self.assertIn("ETH", all_balances)
        self.assertEqual(all_balances["ETH"].total, Decimal("0"))

    def test_get_balance_specific_asset(self) -> None:
        """11. Consulta de saldo para ativo específico e ativo inexistente."""
        self.mock_ccxt.fetch_balance.return_value = {
            "info": {},
            "free": {"USDT": 1250.75},
            "used": {"USDT": 50.25},
            "total": {"USDT": 1301.00},
        }

        usdt_bal = self.client.get_balance("USDT")
        self.assertEqual(usdt_bal.asset, "USDT")
        self.assertEqual(usdt_bal.free, Decimal("1250.75"))
        self.assertEqual(usdt_bal.locked, Decimal("50.25"))
        self.assertEqual(usdt_bal.total, Decimal("1301.00"))

        # Ativo não listado retorna estrutura zerada
        sol_bal = self.client.get_balance("SOL")
        self.assertEqual(sol_bal.asset, "SOL")
        self.assertEqual(sol_bal.free, Decimal("0"))
        self.assertEqual(sol_bal.total, Decimal("0"))

    def test_get_balance_invalid_asset_raises_error(self) -> None:
        """12. Identificador de ativo inválido lança ValueError."""
        with self.assertRaises(ValueError):
            self.client.get_balance("")
        with self.assertRaises(ValueError):
            self.client.get_balance(None)  # type: ignore[arg-type]

    def test_get_account_snapshot_structure(self) -> None:
        """13. Geração completa de AccountSnapshot consolidado."""
        self.mock_ccxt.fetch_balance.return_value = {
            "info": {
                "accountType": "SPOT",
                "canTrade": True,
                "canWithdraw": False,
                "canDeposit": True,
            },
            "free": {"USDT": 1000.0},
            "used": {"USDT": 0.0},
            "total": {"USDT": 1000.0},
        }

        snapshot = self.client.get_account_snapshot()
        self.assertIsInstance(snapshot, AccountSnapshot)
        self.assertEqual(snapshot.source, "binance_private")
        self.assertTrue(snapshot.can_trade)
        self.assertFalse(snapshot.can_withdraw)
        self.assertIn("USDT", snapshot.balances)
        self.assertTrue(len(snapshot.fetched_at) > 0)

    def test_empty_response_handled_gracefully(self) -> None:
        """14. Resposta vazia da exchange é tratada sem lançar exceções não controladas."""
        self.mock_ccxt.fetch_balance.return_value = {}
        status = self.client.get_account_status()
        self.assertFalse(status.can_trade)
        self.assertEqual(status.account_type, "SPOT")

        balances = self.client.get_balances()
        self.assertEqual(len(balances), 0)

    def test_malformed_response_fails_closed(self) -> None:
        """15. Resposta não-dicionário dispara PrivateExchangeError (Fail-Closed)."""
        self.mock_ccxt.fetch_balance.return_value = "MALFORMED_NON_DICT_STRING"
        with self.assertRaises(PrivateExchangeError):
            self.client.get_account_status()

        with self.assertRaises(PrivateExchangeError):
            self.client.get_balances()


class TestPrivateExchangeFailures(unittest.TestCase):
    """Testes de tratamento de falhas e mapeamento de exceções CCXT."""

    def setUp(self) -> None:
        self.cfg = Config(
            trading_mode="live",
            binance_api_key="test_api_key",
            binance_api_secret="test_api_secret",
        )
        self.mock_ccxt = MagicMock()
        self.client = BinancePrivateExchange(self.cfg, client=self.mock_ccxt)

    def test_authentication_failure_mapped(self) -> None:
        """16. ccxt.AuthenticationError mapeado para AuthenticationError."""
        self.mock_ccxt.fetch_balance.side_effect = ccxt.AuthenticationError("Signature invalid")
        with self.assertRaises(AuthenticationError):
            self.client.get_account_status()
        with self.assertRaises(AuthenticationError):
            self.client.get_balances()

    def test_rate_limit_failure_mapped(self) -> None:
        """17. ccxt.RateLimitExceeded mapeado para RateLimitError."""
        self.mock_ccxt.fetch_balance.side_effect = ccxt.RateLimitExceeded("Too many requests (IP ban)")
        with self.assertRaises(RateLimitError):
            self.client.get_account_status()
        with self.assertRaises(RateLimitError):
            self.client.get_balances()

    def test_network_and_timeout_failures_mapped(self) -> None:
        """18. Erros de rede e timeout mapeados para NetworkError."""
        network_errors = [
            ccxt.RequestTimeout("Socket timeout after 10000ms"),
            ccxt.NetworkError("Failed to resolve host api.binance.com"),
            ccxt.ExchangeNotAvailable("Binance Spot maintenance in progress"),
        ]
        for err in network_errors:
            with self.subTest(error=type(err).__name__):
                self.mock_ccxt.fetch_balance.side_effect = err
                with self.assertRaises(NetworkError):
                    self.client.get_account_status()
                with self.assertRaises(NetworkError):
                    self.client.get_balances()

    def test_general_exchange_error_mapped(self) -> None:
        """19. Outros erros da exchange mapeados para PrivateExchangeError."""
        self.mock_ccxt.fetch_balance.side_effect = ccxt.ExchangeError("Internal exchange error 500")
        with self.assertRaises(PrivateExchangeError):
            self.client.get_account_status()
        with self.assertRaises(PrivateExchangeError):
            self.client.get_balances()


class TestArchitecturalOrderBarriers(unittest.TestCase):
    """Testes arquiteturais comprovando a proibição absoluta de ordens na Fase 8.1."""

    def setUp(self) -> None:
        self.cfg = Config(
            trading_mode="live",
            binance_api_key="test_api_key",
            binance_api_secret="test_api_secret",
        )
        self.mock_ccxt = MagicMock()
        self.client = BinancePrivateExchange(self.cfg, client=self.mock_ccxt)

    def test_create_order_is_strictly_blocked(self) -> None:
        """20. Tentativa de invocar create_order é imediatamente bloqueada com LiveTradingBlockedError."""
        with self.assertRaises(LiveTradingBlockedError) as ctx:
            self.client.create_order(symbol="BTC/USDT", side="BUY", amount=1.0)
        self.assertIn("CRITICAL", str(ctx.exception))
        # Garante que nenhum método de ordem foi chamado no cliente subjacente
        self.mock_ccxt.create_order.assert_not_called()

    def test_cancel_order_is_strictly_blocked(self) -> None:
        """21. Tentativa de invocar cancel_order é imediatamente bloqueada com LiveTradingBlockedError."""
        with self.assertRaises(LiveTradingBlockedError) as ctx:
            self.client.cancel_order(order_id="12345", symbol="BTC/USDT")
        self.assertIn("CRITICAL", str(ctx.exception))
        self.mock_ccxt.cancel_order.assert_not_called()

    def test_no_executable_order_methods_exist(self) -> None:
        """22. Verificação reflexiva: nenhum método de ordem pública/privada executável existe no cliente."""
        blocked_keywords = ["order", "trade", "buy", "sell", "withdraw", "deposit"]
        for attr_name in dir(self.client):
            if attr_name.startswith("_"):
                continue
            for kw in blocked_keywords:
                if kw in attr_name.lower():
                    # Se o método contém termo de trading, deve obrigatoriamente levantar LiveTradingBlockedError
                    method = getattr(self.client, attr_name)
                    if callable(method):
                        with self.assertRaises(LiveTradingBlockedError):
                            method()


if __name__ == "__main__":
    unittest.main()
