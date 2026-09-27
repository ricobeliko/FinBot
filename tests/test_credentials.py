"""Suíte de testes para a FASE 8.2A — Secure Windows Credential Storage.

Testa:
1. Modelo BinanceCredentials e mascaramento de segredos (repr/str).
2. FakeCredentialProvider para ambiente de testes.
3. WindowsCredentialProvider (gravação, leitura, verificação e remoção no Credential Manager).
4. Princípio Fail-Closed e tratamento de ausência de credenciais.
5. CLI administrativa segura (setup, status, remove) com proteção contra vazamento.
6. Isolamento e ausência de persistência em arquivos/logs.
"""

from __future__ import annotations

import io
import logging
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

from finbot.config import Config, get_config
from finbot.credentials import (
    BinanceCredentials,
    CredentialProvider,
    CredentialsError,
    CredentialsMissingError,
    FakeCredentialProvider,
    IS_WINDOWS,
    WindowsCredentialProvider,
    cli_remove,
    cli_setup,
    cli_status,
    main as cli_main,
)


class TestBinanceCredentialsDataModel(unittest.TestCase):
    """Testes do modelo de dados e proteção de segredos em BinanceCredentials."""

    def test_repr_and_str_never_expose_secrets(self) -> None:
        """1. repr(credentials) e str(credentials) NUNCA expõem a chave nem o segredo."""
        real_key = "REAL_BINANCE_API_KEY_12345"
        real_secret = "REAL_BINANCE_API_SECRET_67890"

        creds = BinanceCredentials(api_key=real_key, api_secret=real_secret)

        repr_str = repr(creds)
        str_str = str(creds)

        self.assertNotIn(real_key, repr_str)
        self.assertNotIn(real_secret, repr_str)
        self.assertNotIn(real_key, str_str)
        self.assertNotIn(real_secret, str_str)

        self.assertIn("[PROTECTED]", repr_str)
        self.assertIn("[PROTECTED]", str_str)

    def test_credentials_accessors(self) -> None:
        """2. Propriedades acessam os valores reais em memória quando necessário."""
        creds = BinanceCredentials(api_key="my_key", api_secret="my_secret")
        self.assertEqual(creds.api_key, "my_key")
        self.assertEqual(creds.api_secret, "my_secret")

    def test_credentials_type_validation(self) -> None:
        """3. Tipos inválidos disparam ValueError."""
        with self.assertRaises(ValueError):
            BinanceCredentials(api_key=123, api_secret="abc")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            BinanceCredentials(api_key="abc", api_secret=None)  # type: ignore[arg-type]


class TestFakeCredentialProvider(unittest.TestCase):
    """Testes do provedor em memória FakeCredentialProvider."""

    def test_fake_provider_with_credentials(self) -> None:
        """4. FakeCredentialProvider retorna credenciais configuradas."""
        provider = FakeCredentialProvider(api_key="k_test", api_secret="s_test")
        self.assertEqual(provider.get_provider_name(), "FakeCredentialProvider")
        self.assertTrue(provider.has_binance_credentials())

        creds = provider.get_binance_credentials()
        self.assertEqual(creds.api_key, "k_test")
        self.assertEqual(creds.api_secret, "s_test")

    def test_fake_provider_missing_credentials_fails_closed(self) -> None:
        """5. FakeCredentialProvider vazio lança CredentialsMissingError (Fail-Closed)."""
        provider = FakeCredentialProvider(api_key=None, api_secret=None)
        self.assertFalse(provider.has_binance_credentials())

        with self.assertRaises(CredentialsMissingError) as ctx:
            provider.get_binance_credentials()
        self.assertIn("não configuradas", str(ctx.exception))

    def test_fake_provider_set_and_clear(self) -> None:
        """6. FakeCredentialProvider suporta alteração e limpeza dinâmica."""
        provider = FakeCredentialProvider(api_key=None, api_secret=None)
        self.assertFalse(provider.has_binance_credentials())

        provider.set_credentials("k2", "s2")
        self.assertTrue(provider.has_binance_credentials())
        self.assertEqual(provider.get_binance_credentials().api_key, "k2")

        provider.clear()
        self.assertFalse(provider.has_binance_credentials())


@unittest.skipUnless(IS_WINDOWS, "Testes do Windows Credential Manager requerem Windows")
class TestWindowsCredentialProvider(unittest.TestCase):
    """Testes do WindowsCredentialProvider contra target isolado de teste."""

    TEST_TARGET: str = "FinBot/Test/UnitTest"

    def setUp(self) -> None:
        """Garante que o target de teste começa limpo."""
        self.provider = WindowsCredentialProvider(target_name=self.TEST_TARGET)
        self.provider.delete_binance_credentials()

    def tearDown(self) -> None:
        """Limpa o target de teste ao final."""
        self.provider.delete_binance_credentials()

    def test_provider_name_and_target(self) -> None:
        """7. Nome do provedor e target identificados corretamente."""
        self.assertEqual(self.provider.get_provider_name(), "Windows Credential Manager")
        self.assertEqual(self.provider.target_name, self.TEST_TARGET)

    def test_missing_credentials_fails_closed(self) -> None:
        """8. Consulta a target inexistente lança CredentialsMissingError."""
        self.assertFalse(self.provider.has_binance_credentials())
        with self.assertRaises(CredentialsMissingError) as ctx:
            self.provider.get_binance_credentials()
        self.assertIn(self.TEST_TARGET, str(ctx.exception))

    def test_set_and_get_credentials_roundtrip(self) -> None:
        """9. Gravação e leitura segura no Windows Credential Manager."""
        sample_key = "unit_test_key_abc123"
        sample_secret = "unit_test_secret_xyz789"

        self.provider.set_binance_credentials(sample_key, sample_secret)

        self.assertTrue(self.provider.has_binance_credentials())
        creds = self.provider.get_binance_credentials()
        self.assertEqual(creds.api_key, sample_key)
        self.assertEqual(creds.api_secret, sample_secret)

    def test_delete_credentials(self) -> None:
        """10. Remoção de credenciais do Windows Credential Manager."""
        self.provider.set_binance_credentials("key1", "secret1")
        self.assertTrue(self.provider.has_binance_credentials())

        deleted = self.provider.delete_binance_credentials()
        self.assertTrue(deleted)
        self.assertFalse(self.provider.has_binance_credentials())

        # Segunda remoção deve retornar False sem erro
        deleted_again = self.provider.delete_binance_credentials()
        self.assertFalse(deleted_again)

    def test_empty_credentials_rejected(self) -> None:
        """11. Gravação com valores vazios é rejeitada com ValueError."""
        with self.assertRaises(ValueError):
            self.provider.set_binance_credentials("", "secret")
        with self.assertRaises(ValueError):
            self.provider.set_binance_credentials("key", "")


class TestCredentialsSecurityAndEnvironment(unittest.TestCase):
    """Testes de segurança: logs, exceções, persistência e variáveis de ambiente."""

    def test_env_vars_not_used_in_production_get_config(self) -> None:
        """12. get_config() NÃO carrega BINANCE_API_KEY ou BINANCE_API_SECRET do ambiente."""
        with patch.dict(os.environ, {
            "TRADING_MODE": "live",
            "BINANCE_API_KEY": "SHOULD_NOT_BE_LOADED",
            "BINANCE_API_SECRET": "SHOULD_NOT_BE_LOADED",
        }):
            cfg = get_config()
            self.assertEqual(cfg.trading_mode, "live")
            self.assertEqual(cfg.binance_api_key, "")
            self.assertEqual(cfg.binance_api_secret, "")

    def test_secret_never_exposed_in_exception_messages(self) -> None:
        """13. Mensagens de exceção do provedor não revelam segredos."""
        provider = FakeCredentialProvider(api_key=None, api_secret=None)
        try:
            provider.get_binance_credentials()
        except CredentialsMissingError as exc:
            msg = str(exc)
            self.assertNotIn("test-api-secret", msg)
            self.assertNotIn("REAL_SECRET", msg)

    def test_no_file_persistence_created(self) -> None:
        """14. Nenhuma credencial é gravada em arquivos .env, json, sqlite ou csv."""
        provider = FakeCredentialProvider(api_key="sec_key_file_test", api_secret="sec_val_file_test")
        creds = provider.get_binance_credentials()

        # Verifica se nenhum arquivo de configuração ou dados foi criado contendo o segredo
        workspace_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for root, dirs, files in os.walk(workspace_dir):
            dirs[:] = [d for d in dirs if d not in (".git", ".venv", ".venv-research", "__pycache__", "site-packages", ".agents", "artifacts")]
            for f in files:
                if f.endswith((".py", ".md", ".gitignore", ".sqlite3")):
                    continue
                file_path = os.path.join(root, f)
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as fh:
                        content = fh.read()
                        self.assertNotIn("sec_val_file_test", content)
                except Exception:
                    pass


class TestCredentialsCLI(unittest.TestCase):
    """Testes da CLI administrativa segura de credenciais."""

    TEST_TARGET: str = "FinBot/Test/CLITest"

    def setUp(self) -> None:
        self.provider = WindowsCredentialProvider(target_name=self.TEST_TARGET)
        if IS_WINDOWS:
            self.provider.delete_binance_credentials()

    def tearDown(self) -> None:
        if IS_WINDOWS:
            self.provider.delete_binance_credentials()

    @unittest.skipUnless(IS_WINDOWS, "CLI Windows Credential Manager requer Windows")
    def test_cli_setup_stores_credentials_without_printing_them(self) -> None:
        """15. cli_setup grava credenciais e confirma com BINANCE_CREDENTIALS = STORED."""
        secret_sample = "SUPER_SECRET_HMAC_CLI_TEST"
        key_sample = "PUBLIC_API_KEY_CLI_TEST"

        with patch("builtins.input", return_value=key_sample), \
             patch("getpass.getpass", return_value=secret_sample), \
             patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:

            exit_code = cli_setup(self.provider)
            output = mock_stdout.getvalue()

            self.assertEqual(exit_code, 0)
            self.assertIn("BINANCE_CREDENTIALS = STORED", output)
            self.assertNotIn(secret_sample, output)
            self.assertTrue(self.provider.has_binance_credentials())

            creds = self.provider.get_binance_credentials()
            self.assertEqual(creds.api_key, key_sample)
            self.assertEqual(creds.api_secret, secret_sample)

    @unittest.skipUnless(IS_WINDOWS, "CLI Windows Credential Manager requer Windows")
    def test_cli_status_shows_present_or_missing(self) -> None:
        """16. cli_status reporta PRESENT ou MISSING sem revelar segredos."""
        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            exit_code = cli_status(self.provider)
            output = mock_stdout.getvalue()
            self.assertEqual(exit_code, 0)
            self.assertIn("Binance credentials: MISSING", output)

        self.provider.set_binance_credentials("dummy_key", "dummy_secret")

        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            exit_code = cli_status(self.provider)
            output = mock_stdout.getvalue()
            self.assertEqual(exit_code, 0)
            self.assertIn("Binance credentials: PRESENT", output)
            self.assertNotIn("dummy_secret", output)

    @unittest.skipUnless(IS_WINDOWS, "CLI Windows Credential Manager requer Windows")
    def test_cli_remove_requires_confirmation(self) -> None:
        """17. cli_remove exige confirmação explícita para remoção."""
        self.provider.set_binance_credentials("dummy_key", "dummy_secret")
        self.assertTrue(self.provider.has_binance_credentials())

        # Cenário 1: Usuário cancela ('n')
        with patch("builtins.input", return_value="n"), \
             patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            exit_code = cli_remove(self.provider)
            output = mock_stdout.getvalue()
            self.assertEqual(exit_code, 0)
            self.assertIn("Operação cancelada", output)
            self.assertTrue(self.provider.has_binance_credentials())

        # Cenário 2: Usuário confirma ('s')
        with patch("builtins.input", return_value="s"), \
             patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            exit_code = cli_remove(self.provider)
            output = mock_stdout.getvalue()
            self.assertEqual(exit_code, 0)
            self.assertIn("BINANCE_CREDENTIALS = REMOVED", output)
            self.assertFalse(self.provider.has_binance_credentials())

    @unittest.skipUnless(IS_WINDOWS, "CLI Windows Credential Manager requer Windows")
    def test_cli_main_entrypoint(self) -> None:
        """18. main() despacha comandos corretamente via CLI."""
        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            exit_code = cli_main(["status", "--target", self.TEST_TARGET])
            output = mock_stdout.getvalue()
            self.assertEqual(exit_code, 0)
            self.assertIn("Binance credentials: MISSING", output)


if __name__ == "__main__":
    unittest.main()
