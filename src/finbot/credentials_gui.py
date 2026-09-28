"""Módulo de interface gráfica local segura para cadastro de credenciais da Binance (FASE 8.2B).

Fornece uma interface gráfica simples, local e segura (Tkinter) para cadastrar
ou atualizar API Key e API Secret da Binance diretamente no Windows Credential Manager,
eliminando falhas de colagem/ocultação ocorridas no terminal (getpass).

REGRAS DE SEGURANÇA:
1. NUNCA salvar credenciais em arquivos (.env, json, yaml, toml, txt, sqlite, csv).
2. NUNCA exibir API Key ou API Secret em logs, terminal, exceções ou caixas de diálogo.
3. O campo de API Secret deve ser mascarado visualmente por padrão (show="*").
4. Strip apenas nas extremidades; validação preventiva contra valores truncados (SECRET_LEN curto).
5. Armazenamento EXCLUSIVO via WindowsCredentialProvider no Windows Credential Manager.
6. Nenhuma chamada à API da Binance é realizada no momento do cadastro.
7. Nenhum trade, ordem ou operação real é permitida.
"""

from __future__ import annotations

import argparse
import logging
import sys
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

from finbot.credentials import (
    BinanceCredentials,
    CredentialProvider,
    CredentialsError,
    WindowsCredentialProvider,
)

logger = logging.getLogger(__name__)

# Comprimento mínimo para prevenção contra colagens truncadas (ex.: SECRET_LEN=2).
# Chaves HMAC na Binance têm 64 caracteres hexadecimais; 16 é um limite preventivo seguro sem ser rígido.
MIN_CREDENTIAL_LENGTH = 16


def validate_credentials(api_key: str, api_secret: str) -> tuple[bool, str]:
    """Valida preventivamente campos de credenciais sem expor conteúdos sensíveis.

    Retorna (True, "") se válido, ou (False, mensagem_segura) em caso de erro.
    """
    if not isinstance(api_key, str) or not isinstance(api_secret, str):
        return False, "Os campos API Key e API Secret devem ser texto."

    clean_key = api_key.strip()
    clean_secret = api_secret.strip()

    if not clean_key or not clean_secret:
        return False, "Preencha todos os campos obrigatórios (API Key e API Secret)."

    if "\n" in clean_key or "\r" in clean_key or "\n" in clean_secret or "\r" in clean_secret:
        return False, "Quebras de linha não são permitidas nas credenciais."

    if len(clean_key) < MIN_CREDENTIAL_LENGTH or len(clean_secret) < MIN_CREDENTIAL_LENGTH:
        return False, (
            "Credenciais com comprimento insuficiente. "
            "Verifique se a chave e o segredo foram copiados integralmente."
        )

    return True, ""


def enroll_credentials(
    api_key: str,
    api_secret: str,
    provider: CredentialProvider | None = None,
) -> tuple[bool, str]:
    """Valida e armazena credenciais no provedor de forma segura.

    NUNCA imprime, registra em log ou expõe o segredo em exceções.
    """
    is_valid, error_msg = validate_credentials(api_key, api_secret)
    if not is_valid:
        return False, error_msg

    clean_key = api_key.strip()
    clean_secret = api_secret.strip()

    if provider is None:
        provider = WindowsCredentialProvider()

    try:
        if hasattr(provider, "set_binance_credentials"):
            provider.set_binance_credentials(clean_key, clean_secret)
        elif hasattr(provider, "set_credentials"):
            provider.set_credentials(clean_key, clean_secret)
        else:
            return False, "Provedor de credenciais não suporta operação de gravação."

        logger.info(
            "Credenciais da Binance armazenadas com segurança via GUI (store=%s).",
            provider.get_provider_name(),
        )
        return True, "Credenciais Binance armazenadas com segurança."
    except Exception as exc:
        logger.error(
            "Falha ao armazenar credenciais no cofre: %s",
            exc.__class__.__name__,
        )
        return False, f"Erro ao armazenar credenciais: {exc.__class__.__name__}."


class CredentialsApp:
    """Janela Tkinter para cadastro seguro de credenciais da Binance."""

    def __init__(
        self,
        root: tk.Tk | tk.Toplevel,
        provider: CredentialProvider | None = None,
        auto_close_on_success: bool = True,
    ) -> None:
        self.root = root
        self.provider = provider or WindowsCredentialProvider()
        self.auto_close_on_success = auto_close_on_success

        self.root.title("FinBot — Binance Credentials")
        self.root.resizable(False, False)

        # Variáveis de controle
        self.show_secret_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="")

        self._build_ui()
        self._center_window(520, 360)

    def _center_window(self, width: int, height: int) -> None:
        """Centraliza a janela na tela do operador."""
        try:
            self.root.update_idletasks()
            screen_width = self.root.winfo_screenwidth()
            screen_height = self.root.winfo_screenheight()
            x = max(0, (screen_width - width) // 2)
            y = max(0, (screen_height - height) // 2)
            self.root.geometry(f"{width}x{height}+{x}+{y}")
        except Exception:
            self.root.geometry(f"{width}x{height}")

    def _build_ui(self) -> None:
        """Constrói os componentes da interface visual."""
        padding = 16

        container = ttk.Frame(self.root, padding=padding)
        container.pack(fill=tk.BOTH, expand=True)

        # Cabeçalho informativo
        title_label = ttk.Label(
            container,
            text="FinBot — Binance Credentials",
            font=("Segoe UI", 12, "bold"),
        )
        title_label.pack(anchor=tk.W, pady=(0, 2))

        target_name = getattr(self.provider, "target_name", self.provider.get_provider_name())
        subtitle_label = ttk.Label(
            container,
            text=(
                f"Armazenamento: {self.provider.get_provider_name()} (Target: {target_name})\n"
                "Permissões necessárias: Apenas Leitura (HMAC Read-Only)"
            ),
            font=("Segoe UI", 9),
            foreground="#555555",
        )
        subtitle_label.pack(anchor=tk.W, pady=(0, 10))

        ttk.Separator(container, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(0, 12))

        # Campo: API Key
        key_label = ttk.Label(container, text="API Key:", font=("Segoe UI", 9, "bold"))
        key_label.pack(anchor=tk.W, pady=(0, 2))

        self.entry_key = ttk.Entry(container, width=54)
        self.entry_key.pack(fill=tk.X, pady=(0, 10))
        self.entry_key.focus_set()

        # Campo: API Secret (mascarado com asteriscos por padrão)
        secret_label = ttk.Label(container, text="API Secret:", font=("Segoe UI", 9, "bold"))
        secret_label.pack(anchor=tk.W, pady=(0, 2))

        self.entry_secret = ttk.Entry(container, width=54, show="*")
        self.entry_secret.pack(fill=tk.X, pady=(0, 4))

        # Opção: Mostrar/Ocultar Secret
        self.check_show_secret = ttk.Checkbutton(
            container,
            text="Mostrar API Secret",
            variable=self.show_secret_var,
            command=self._on_toggle_show_secret,
        )
        self.check_show_secret.pack(anchor=tk.W, pady=(0, 10))

        # Label para mensagens de status e validação
        self.label_status = ttk.Label(
            container,
            textvariable=self.status_var,
            font=("Segoe UI", 9),
            wraplength=480,
        )
        self.label_status.pack(anchor=tk.W, pady=(0, 10))

        # Barra de botões inferior
        btn_frame = ttk.Frame(container)
        btn_frame.pack(fill=tk.X, side=tk.BOTTOM, pady=(8, 0))

        self.btn_cancel = ttk.Button(btn_frame, text="Cancelar", command=self.on_cancel)
        self.btn_cancel.pack(side=tk.RIGHT, padx=(6, 0))

        self.btn_save = ttk.Button(
            btn_frame, text="Salvar com segurança", command=self.on_save
        )
        self.btn_save.pack(side=tk.RIGHT)

    def _on_toggle_show_secret(self) -> None:
        """Alterna a exibição mascarada do API Secret."""
        if self.show_secret_var.get():
            self.entry_secret.config(show="")
        else:
            self.entry_secret.config(show="*")

    def _clear_inputs(self) -> None:
        """Limpa campos de entrada em memória na GUI."""
        self.entry_key.delete(0, tk.END)
        self.entry_secret.delete(0, tk.END)
        self.show_secret_var.set(False)
        self.entry_secret.config(show="*")

    def on_save(self) -> None:
        """Executa a validação e salvamento seguro das credenciais."""
        key = self.entry_key.get()
        secret = self.entry_secret.get()

        success, message = enroll_credentials(key, secret, provider=self.provider)

        if not success:
            self.status_var.set(message)
            self.label_status.config(foreground="#b00020")
            messagebox.showerror("Erro de Validação", message, parent=self.root)
            return

        # Limpeza imediata dos campos após sucesso
        self._clear_inputs()
        self.status_var.set(message)
        self.label_status.config(foreground="#007700")

        messagebox.showinfo("Sucesso", message, parent=self.root)

        if self.auto_close_on_success:
            self.root.destroy()

    def on_cancel(self) -> None:
        """Cancela a operação limpando os campos e fechando a janela."""
        self._clear_inputs()
        self.root.destroy()


def run_gui(
    provider: CredentialProvider | None = None,
    auto_close_on_success: bool = True,
) -> int:
    """Inicializa e executa a interface gráfica local."""
    root = tk.Tk()
    app = CredentialsApp(
        root, provider=provider, auto_close_on_success=auto_close_on_success
    )
    root.mainloop()
    return 0


def main(argv: list[str] | None = None) -> int:
    """Ponto de entrada CLI para abertura da GUI de credenciais."""
    parser = argparse.ArgumentParser(
        prog="python -m finbot.credentials_gui",
        description="Interface gráfica local segura para cadastro de credenciais da Binance.",
    )
    parser.add_argument(
        "--target",
        default=WindowsCredentialProvider.DEFAULT_TARGET_NAME,
        help="Nome do target no Windows Credential Manager (default: FinBot/Binance/Production)",
    )
    args = parser.parse_args(argv)
    provider = WindowsCredentialProvider(target_name=args.target)
    return run_gui(provider=provider)


if __name__ == "__main__":
    sys.exit(main())
