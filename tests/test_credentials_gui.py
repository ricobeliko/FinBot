"""Suíte de testes para a FASE 8.2B — GUI Local Segura para Cadastro de Credenciais Binance.

Testa:
1. Validações preventivas de entrada (campos vazios, espaços, quebras de linha, comprimento insuficiente).
2. Isolamento de segredos (chave e segredo NUNCA aparecem em mensagens de erro, logs ou exceções).
3. Função enroll_credentials com FakeCredentialProvider.
4. Ausência de persistência em arquivos de sistema.
5. Inicialização e lógica de eventos da GUI Tkinter em modo headless (sem abrir janelas interativas).
6. Integração da CLI em credentials_gui e credentials.
"""

from __future__ import annotations

import io
import logging
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

from finbot.credentials import (
    BinanceCredentials,
    FakeCredentialProvider,
    WindowsCredentialProvider,
    main as credentials_cli_main,
)
from finbot.credentials_gui import (
    MIN_CREDENTIAL_LENGTH,
    CredentialsApp,
    enroll_credentials,
    main as gui_cli_main,
    validate_credentials,
)

import tkinter as tk


class TestCredentialsValidation(unittest.TestCase):
    """Testes unitários para a função validate_credentials."""

    def test_empty_fields_rejected(self) -> None:
        """1. Campos vazios ou apenas com espaços são categoricamente rejeitados."""
        is_valid, msg = validate_credentials("", "")
        self.assertFalse(is_valid)
        self.assertIn("obrigatórios", msg)

        is_valid, msg = validate_credentials("   ", "   ")
        self.assertFalse(is_valid)
        self.assertIn("obrigatórios", msg)

        is_valid, msg = validate_credentials("valid_key_12345678", "")
        self.assertFalse(is_valid)
        self.assertIn("obrigatórios", msg)

        is_valid, msg = validate_credentials("", "valid_secret_12345678")
        self.assertFalse(is_valid)
        self.assertIn("obrigatórios", msg)

    def test_non_string_types_rejected(self) -> None:
        """2. Tipos diferentes de string são rejeitados com segurança."""
        is_valid, msg = validate_credentials(12345, "secret_1234567890")  # type: ignore[arg-type]
        self.assertFalse(is_valid)
        self.assertIn("texto", msg)

    def test_newlines_rejected(self) -> None:
        """3. Quebras de linha nas credenciais são rejeitadas."""
        is_valid, msg = validate_credentials("key_line1\nkey_line2", "secret_123456789012")
        self.assertFalse(is_valid)
        self.assertIn("Quebras de linha", msg)

        is_valid, msg = validate_credentials("key_12345678901234", "secret\r\nline2")
        self.assertFalse(is_valid)
        self.assertIn("Quebras de linha", msg)

    def test_absurdly_short_credentials_rejected(self) -> None:
        """4. Credenciais muito curtas (< 16 caracteres, ex: SECRET_LEN=2) são rejeitadas."""
        # Caso real ocorrido no PC Forte: colagem truncada gerando len=2
        short_secret = "a1"
        valid_key = "k" * 64

        is_valid, msg = validate_credentials(valid_key, short_secret)
        self.assertFalse(is_valid)
        self.assertIn("comprimento insuficiente", msg)
        self.assertNotIn(short_secret, msg)
        self.assertNotIn(valid_key, msg)

        # Chave curta
        is_valid, msg = validate_credentials("short_key", "s" * 64)
        self.assertFalse(is_valid)
        self.assertIn("comprimento insuficiente", msg)

    def test_valid_credentials_accepted(self) -> None:
        """5. Credenciais com comprimento adequado e formato limpo são aceitas."""
        sample_key = "k" * 64
        sample_secret = "s" * 64
        is_valid, msg = validate_credentials(sample_key, sample_secret)
        self.assertTrue(is_valid)
        self.assertEqual(msg, "")


class TestEnrollCredentialsLogic(unittest.TestCase):
    """Testes para o fluxo de salvamento de credenciais via enroll_credentials."""

    def test_enroll_success_with_fake_provider(self) -> None:
        """6. Gravação bem-sucedida usando FakeCredentialProvider."""
        provider = FakeCredentialProvider(api_key=None, api_secret=None)
        key_input = "  " + ("k" * 64) + "  "
        secret_input = "  " + ("s" * 64) + "  "

        success, msg = enroll_credentials(key_input, secret_input, provider=provider)

        self.assertTrue(success)
        self.assertEqual(msg, "Credenciais Binance armazenadas com segurança.")

        # Verifica se o provider recebeu os valores com strip nas extremidades
        self.assertTrue(provider.has_binance_credentials())
        creds = provider.get_binance_credentials()
        self.assertEqual(creds.api_key, "k" * 64)
        self.assertEqual(creds.api_secret, "s" * 64)

    def test_enroll_validation_failure_does_not_call_provider(self) -> None:
        """7. Falha de validação não invoca o provider e retorna erro seguro."""
        provider = FakeCredentialProvider(api_key=None, api_secret=None)

        success, msg = enroll_credentials("too_short", "s" * 64, provider=provider)
        self.assertFalse(success)
        self.assertIn("comprimento insuficiente", msg)
        self.assertFalse(provider.has_binance_credentials())

    def test_provider_error_does_not_reveal_secrets(self) -> None:
        """8. Exceções geradas pelo provedor não vazam a chave ou segredo no retorno ou no log."""
        secret_val = "SECRET_SUPER_CONFIDENTIAL_12345678"
        key_val = "KEY_SUPER_CONFIDENTIAL_123456789012"

        mock_provider = MagicMock()
        mock_provider.get_provider_name.return_value = "MockVault"
        mock_provider.set_binance_credentials.side_effect = RuntimeError(
            f"Vault lock failed while processing {secret_val}"
        )

        with self.assertLogs("finbot.credentials_gui", level="ERROR") as log_capture:
            success, msg = enroll_credentials(key_val, secret_val, provider=mock_provider)

        self.assertFalse(success)
        self.assertNotIn(secret_val, msg)
        self.assertNotIn(key_val, msg)
        self.assertIn("RuntimeError", msg)

        # Verifica logs
        log_text = " ".join(log_capture.output)
        self.assertNotIn(secret_val, log_text)
        self.assertNotIn(key_val, log_text)

    def test_no_file_persistence_created(self) -> None:
        """9. Nenhuma credencial é gravada em arquivos durante o cadastro via enroll_credentials."""
        provider = FakeCredentialProvider(api_key=None, api_secret=None)
        secret_probe = "PROBE_SECRET_NO_FILE_ABC123456789"
        key_probe = "PROBE_KEY_NO_FILE_ABC123456789012"

        enroll_credentials(key_probe, secret_probe, provider=provider)

        workspace_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for root, dirs, files in os.walk(workspace_dir):
            dirs[:] = [
                d
                for d in dirs
                if d
                not in (
                    ".git",
                    ".venv",
                    ".venv-research",
                    "__pycache__",
                    "site-packages",
                    ".agents",
                    "artifacts",
                )
            ]
            for f in files:
                if f.endswith((".py", ".md", ".gitignore", ".sqlite3")):
                    continue
                file_path = os.path.join(root, f)
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as fh:
                        content = fh.read()
                        self.assertNotIn(secret_probe, content)
                except Exception:
                    pass


class TestCredentialsAppUI(unittest.TestCase):
    """Testes dos componentes e eventos da CredentialsApp em modo headless."""

    def setUp(self) -> None:
        self.root = tk.Tk()
        self.root.withdraw()  # Não abre janela visual durante testes
        self.provider = FakeCredentialProvider(api_key=None, api_secret=None)
        self.app = CredentialsApp(
            self.root,
            provider=self.provider,
            auto_close_on_success=True,
        )

    def tearDown(self) -> None:
        try:
            self.root.destroy()
        except Exception:
            pass

    def test_ui_initial_state(self) -> None:
        """10. Estado inicial da UI: secret mascarado com show='*' e título correto."""
        self.assertEqual(self.root.title(), "FinBot — Binance Credentials")
        self.assertEqual(self.app.entry_secret.cget("show"), "*")
        self.assertFalse(self.app.show_secret_var.get())
        self.assertEqual(self.app.entry_key.get(), "")
        self.assertEqual(self.app.entry_secret.get(), "")

    def test_toggle_show_secret(self) -> None:
        """11. Alternância da máscara do segredo via checkbox."""
        # Marcar para mostrar
        self.app.show_secret_var.set(True)
        self.app._on_toggle_show_secret()
        self.assertEqual(self.app.entry_secret.cget("show"), "")

        # Desmarcar para ocultar
        self.app.show_secret_var.set(False)
        self.app._on_toggle_show_secret()
        self.assertEqual(self.app.entry_secret.cget("show"), "*")

    @patch("tkinter.messagebox.showerror")
    def test_on_save_validation_error(self, mock_showerror: MagicMock) -> None:
        """12. Salvar com campos inválidos exibe erro e não limpa entradas."""
        self.app.entry_key.insert(0, "short")
        self.app.entry_secret.insert(0, "s")

        self.app.on_save()

        mock_showerror.assert_called_once()
        # Campos permanecem preenchidos para que o operador possa corrigir
        self.assertEqual(self.app.entry_key.get(), "short")
        self.assertEqual(self.app.entry_secret.get(), "s")
        self.assertFalse(self.provider.has_binance_credentials())

    @patch("tkinter.messagebox.showinfo")
    def test_on_save_success_clears_inputs(self, mock_showinfo: MagicMock) -> None:
        """13. Salvar com sucesso grava no provedor, limpa campos e fecha janela."""
        key_input = "k" * 64
        secret_input = "s" * 64

        self.app.entry_key.insert(0, key_input)
        self.app.entry_secret.insert(0, secret_input)

        with patch.object(self.root, "destroy") as mock_destroy:
            self.app.on_save()
            mock_showinfo.assert_called_once()
            args, _ = mock_showinfo.call_args
            self.assertIn("Credenciais Binance armazenadas com segurança.", args[1])
            self.assertNotIn(key_input, args[1])
            self.assertNotIn(secret_input, args[1])

            # Verifica limpeza de inputs
            self.assertEqual(self.app.entry_key.get(), "")
            self.assertEqual(self.app.entry_secret.get(), "")
            self.assertEqual(self.app.entry_secret.cget("show"), "*")

            # Verifica gravação no provedor
            self.assertTrue(self.provider.has_binance_credentials())
            self.assertEqual(self.provider.get_binance_credentials().api_key, key_input)

            # Verifica fechamento da janela
            mock_destroy.assert_called_once()

    def test_on_cancel_clears_and_closes(self) -> None:
        """14. Cancelar limpa os campos e fecha a janela."""
        self.app.entry_key.insert(0, "sensitive_key_123456789")
        self.app.entry_secret.insert(0, "sensitive_secret_123456789")

        with patch.object(self.root, "destroy") as mock_destroy:
            self.app.on_cancel()
            self.assertEqual(self.app.entry_key.get(), "")
            self.assertEqual(self.app.entry_secret.get(), "")
            mock_destroy.assert_called_once()


class TestCredentialsGUICLI(unittest.TestCase):
    """Testes dos comandos CLI de invocação da GUI."""

    @patch("finbot.credentials_gui.run_gui", return_value=0)
    def test_gui_main_cli_entrypoint(self, mock_run_gui: MagicMock) -> None:
        """15. python -m finbot.credentials_gui instancia e executa a GUI."""
        exit_code = gui_cli_main(["--target", "FinBot/Test/Target"])
        self.assertEqual(exit_code, 0)
        mock_run_gui.assert_called_once()
        provider = mock_run_gui.call_args[1]["provider"]
        self.assertEqual(provider.target_name, "FinBot/Test/Target")

    @patch("finbot.credentials_gui.run_gui", return_value=0)
    def test_credentials_gui_subcommand_dispatch(self, mock_run_gui: MagicMock) -> None:
        """16. python -m finbot.credentials gui despacha corretamente para run_gui."""
        exit_code = credentials_cli_main(["gui", "--target", "FinBot/Test/Target"])
        self.assertEqual(exit_code, 0)
        mock_run_gui.assert_called_once()


if __name__ == "__main__":
    unittest.main()
