"""Módulo de gerenciamento seguro de credenciais via Windows Credential Manager (FASE 8.2A).

Fornece armazenamento seguro e nativo para credenciais de API da Binance, eliminando
a necessidade de arquivos de texto (.env, json, yaml), variáveis de ambiente ou persistência em banco.

REGRAS DE SEGURANÇA:
1. NUNCA salvar credenciais em arquivos temporários ou persistentes (.env, json, sqlite, csv).
2. NUNCA exibir API Key ou API Secret em logs, exceções, terminal ou __repr__/__str__.
3. FAIL-CLOSED: Se as credenciais não existirem no Windows Credential Manager, falha imediatamente.
4. ISOLAMENTO: Paper Trading NÃO consulta nem necessita de credenciais privadas.
5. PROVEDORES: Suporte a WindowsCredentialProvider (produção) e FakeCredentialProvider (testes).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import argparse
from dataclasses import dataclass, field
import getpass
import logging
import sys
from typing import Any

logger = logging.getLogger(__name__)

# =============================================================================
# EXCEÇÕES DE SEGURANÇA E GERENCIAMENTO DE CREDENCIAIS
# =============================================================================


class CredentialsError(Exception):
    """Exceção base para erros de obtenção ou manipulação de credenciais."""


class CredentialsMissingError(CredentialsError):
    """Lançada quando credenciais necessárias estão ausentes no provedor."""


# =============================================================================
# ESTRUTURA DE DADOS DE CREDENCIAIS
# =============================================================================


@dataclass(frozen=True)
class BinanceCredentials:
    """Credenciais de API da Binance com proteção estrita contra vazamento."""

    api_key: str = field(repr=False)
    api_secret: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.api_key, str) or not isinstance(self.api_secret, str):
            raise ValueError("api_key e api_secret devem ser strings.")

    def __repr__(self) -> str:
        """Representação mascarada que NUNCA expõe chaves ou segredos."""
        return "BinanceCredentials(api_key=[PROTECTED], api_secret=[PROTECTED])"

    def __str__(self) -> str:
        return self.__repr__()


# =============================================================================
# INTERFACE DO PROVEDOR DE CREDENCIAIS
# =============================================================================


class CredentialProvider(ABC):
    """Interface abstrata para provedores de credenciais da Binance."""

    @abstractmethod
    def get_provider_name(self) -> str:
        """Retorna o nome amigável do provedor."""

    @abstractmethod
    def get_binance_credentials(self) -> BinanceCredentials:
        """Obtém as credenciais da Binance. Lança CredentialsMissingError se ausentes."""

    @abstractmethod
    def has_binance_credentials(self) -> bool:
        """Verifica com segurança se as credenciais estão presentes."""


# =============================================================================
# IMPLEMENTAÇÃO WINDOWS CREDENTIAL MANAGER (NATIVO VIA CTYPES / ADVAPI32)
# =============================================================================

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2
    ERROR_NOT_FOUND = 1168

    class FILETIME(ctypes.Structure):
        _fields_ = [
            ("dwLowDateTime", wintypes.DWORD),
            ("dwHighDateTime", wintypes.DWORD),
        ]

    class CREDENTIALW(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    PCREDENTIALW = ctypes.POINTER(CREDENTIALW)

    _advapi32 = ctypes.windll.advapi32

    _advapi32.CredReadW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(PCREDENTIALW),
    ]
    _advapi32.CredReadW.restype = wintypes.BOOL

    _advapi32.CredWriteW.argtypes = [
        PCREDENTIALW,
        wintypes.DWORD,
    ]
    _advapi32.CredWriteW.restype = wintypes.BOOL

    _advapi32.CredDeleteW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    _advapi32.CredDeleteW.restype = wintypes.BOOL

    _advapi32.CredFree.argtypes = [ctypes.c_void_p]
    _advapi32.CredFree.restype = None


class WindowsCredentialProvider(CredentialProvider):
    """Provedor de credenciais nativo baseado no Windows Credential Manager.

    Armazena e recupera credenciais usando a API Crypto / CredReadW da Advapi32.
    """

    DEFAULT_TARGET_NAME: str = "FinBot/Binance/Production"

    def __init__(self, target_name: str = DEFAULT_TARGET_NAME) -> None:
        self.target_name = target_name

    def get_provider_name(self) -> str:
        return "Windows Credential Manager"

    def get_binance_credentials(self) -> BinanceCredentials:
        """Recupera credenciais da Binance do Windows Credential Manager.

        Lança CredentialsMissingError se o target não existir ou os dados forem vazios.
        """
        if not IS_WINDOWS:
            raise NotImplementedError("WindowsCredentialProvider é suportado exclusivamente no Windows.")

        p_cred = PCREDENTIALW()
        ret = _advapi32.CredReadW(self.target_name, CRED_TYPE_GENERIC, 0, ctypes.byref(p_cred))
        if not ret:
            err = ctypes.GetLastError()
            if err == ERROR_NOT_FOUND:
                raise CredentialsMissingError(
                    f"Credenciais da Binance não encontradas no Windows Credential Manager (target='{self.target_name}')."
                )
            raise CredentialsError(f"Erro ao consultar o Windows Credential Manager: código de erro {err}.")

        try:
            user_name = p_cred.contents.UserName
            blob_size = p_cred.contents.CredentialBlobSize
            blob_ptr = p_cred.contents.CredentialBlob

            if not user_name or blob_size == 0 or not blob_ptr:
                raise CredentialsMissingError(
                    f"Credenciais corrompidas ou vazias no Windows Credential Manager (target='{self.target_name}')."
                )

            raw_secret = ctypes.string_at(blob_ptr, blob_size).decode("utf-8")
            return BinanceCredentials(api_key=user_name.strip(), api_secret=raw_secret.strip())
        finally:
            _advapi32.CredFree(p_cred)

    def has_binance_credentials(self) -> bool:
        """Verifica se credenciais válidas estão gravadas no Windows Credential Manager."""
        if not IS_WINDOWS:
            return False

        p_cred = PCREDENTIALW()
        ret = _advapi32.CredReadW(self.target_name, CRED_TYPE_GENERIC, 0, ctypes.byref(p_cred))
        if not ret:
            return False

        try:
            user_name = p_cred.contents.UserName
            blob_size = p_cred.contents.CredentialBlobSize
            blob_ptr = p_cred.contents.CredentialBlob
            return bool(user_name and blob_size > 0 and blob_ptr)
        finally:
            _advapi32.CredFree(p_cred)

    def set_binance_credentials(self, api_key: str, api_secret: str) -> None:
        """Grava credenciais no Windows Credential Manager de forma segura."""
        if not IS_WINDOWS:
            raise NotImplementedError("WindowsCredentialProvider é suportado exclusivamente no Windows.")

        key = api_key.strip()
        secret = api_secret.strip()

        if not key or not secret:
            raise ValueError("API Key e API Secret não podem ser vazios.")

        secret_bytes = secret.encode("utf-8")
        blob_buffer = (ctypes.c_byte * len(secret_bytes))(*secret_bytes)

        cred = CREDENTIALW()
        cred.Flags = 0
        cred.Type = CRED_TYPE_GENERIC
        cred.TargetName = self.target_name
        cred.Comment = "FinBot Binance Spot API Credentials"
        cred.CredentialBlobSize = len(secret_bytes)
        cred.CredentialBlob = ctypes.cast(blob_buffer, ctypes.POINTER(ctypes.c_byte))
        cred.Persist = CRED_PERSIST_LOCAL_MACHINE
        cred.AttributeCount = 0
        cred.Attributes = None
        cred.TargetAlias = None
        cred.UserName = key

        ret = _advapi32.CredWriteW(ctypes.byref(cred), 0)
        if not ret:
            err = ctypes.GetLastError()
            raise CredentialsError(f"Falha ao gravar no Windows Credential Manager: código de erro {err}.")

    def delete_binance_credentials(self) -> bool:
        """Remove credenciais do Windows Credential Manager.

        Retorna True se removido com sucesso, False se já não existia.
        """
        if not IS_WINDOWS:
            return False

        ret = _advapi32.CredDeleteW(self.target_name, CRED_TYPE_GENERIC, 0)
        if not ret:
            err = ctypes.GetLastError()
            if err == ERROR_NOT_FOUND:
                return False
            raise CredentialsError(f"Erro ao remover credencial do Windows Credential Manager: código de erro {err}.")
        return True


# =============================================================================
# IMPLEMENTAÇÃO PARA TESTES / ISOLAMENTO (FAKE CREDENTIAL PROVIDER)
# =============================================================================


class FakeCredentialProvider(CredentialProvider):
    """Provedor em memória para testes unitários, isolado do Credential Manager do sistema."""

    def __init__(
        self,
        api_key: str | None = "test-api-key",
        api_secret: str | None = "test-api-secret",
        provider_name: str = "FakeCredentialProvider",
    ) -> None:
        self._provider_name = provider_name
        clean_key = (api_key or "").strip()
        clean_secret = (api_secret or "").strip()
        if clean_key and clean_secret:
            self._credentials: BinanceCredentials | None = BinanceCredentials(
                api_key=clean_key, api_secret=clean_secret
            )
        else:
            self._credentials = None

    def get_provider_name(self) -> str:
        return self._provider_name

    def has_binance_credentials(self) -> bool:
        return self._credentials is not None

    def get_binance_credentials(self) -> BinanceCredentials:
        if self._credentials is None:
            raise CredentialsMissingError(
                f"Credenciais da Binance não configuradas no {self.get_provider_name()}."
            )
        return self._credentials

    def set_credentials(self, api_key: str, api_secret: str) -> None:
        clean_key = (api_key or "").strip()
        clean_secret = (api_secret or "").strip()
        if not clean_key or not clean_secret:
            raise ValueError("API Key e API Secret não podem ser vazios.")
        self._credentials = BinanceCredentials(api_key=clean_key, api_secret=clean_secret)

    def set_binance_credentials(self, api_key: str, api_secret: str) -> None:
        """Compatibilidade com a interface do WindowsCredentialProvider."""
        self.set_credentials(api_key, api_secret)

    def clear(self) -> None:
        self._credentials = None



# =============================================================================
# CLI ADMINISTRATIVA E SEGURA
# =============================================================================


def cli_setup(provider: WindowsCredentialProvider) -> int:
    """Configura credenciais de forma segura sem impressão no terminal."""
    print("=== FinBot: Configuração Segura de Credenciais da Binance ===")
    print("Armazenamento: Windows Credential Manager")
    print(f"Target: {provider.target_name}")
    print("Aviso: Chaves devem possuir EXCLUSIVAMENTE permissão de leitura.")
    print("-" * 55)

    try:
        api_key = input("Binance API Key: ").strip()
        api_secret = getpass.getpass("Binance API Secret (entrada oculta): ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nOperação cancelada.")
        return 1

    if not api_key or not api_secret:
        print("ERRO: API Key e API Secret não podem ser vazios.")
        return 1

    try:
        provider.set_binance_credentials(api_key, api_secret)
        print("BINANCE_CREDENTIALS = STORED")
        return 0
    except Exception as exc:
        print(f"ERRO ao armazenar credenciais: {exc}")
        return 1


def cli_status(provider: WindowsCredentialProvider) -> int:
    """Verifica com segurança se as credenciais estão cadastradas."""
    try:
        is_present = provider.has_binance_credentials()
        status_str = "PRESENT" if is_present else "MISSING"
        print(f"Credential store: {provider.get_provider_name()}")
        print(f"Target: {provider.target_name}")
        print(f"Binance credentials: {status_str}")
        return 0
    except Exception as exc:
        print(f"ERRO ao verificar status: {exc}")
        return 1


def cli_remove(provider: WindowsCredentialProvider) -> int:
    """Remove credenciais mediante confirmação explícita do operador."""
    if not provider.has_binance_credentials():
        print("Nenhuma credencial encontrada no Windows Credential Manager.")
        return 0

    print("=== FinBot: Remoção de Credenciais da Binance ===")
    print(f"Target: {provider.target_name}")
    try:
        confirm = input(
            "Tem certeza que deseja remover as credenciais da Binance do Windows Credential Manager? [s/N]: "
        ).strip().lower()
    except (KeyboardInterrupt, EOFError):
        print("\nOperação cancelada. Credenciais mantidas.")
        return 1

    if confirm in ("s", "sim", "y", "yes"):
        try:
            removed = provider.delete_binance_credentials()
            if removed:
                print("BINANCE_CREDENTIALS = REMOVED")
            else:
                print("BINANCE_CREDENTIALS = NOT_FOUND")
            return 0
        except Exception as exc:
            print(f"ERRO ao remover credenciais: {exc}")
            return 1
    else:
        print("Operação cancelada pelo usuário. Credenciais mantidas.")
        return 0


def main(argv: list[str] | None = None) -> int:
    """Ponto de entrada para CLI administrativa de credenciais."""
    parser = argparse.ArgumentParser(
        prog="python -m finbot.credentials",
        description="Gerenciador seguro de credenciais da Binance no Windows Credential Manager.",
    )
    parser.add_argument(
        "action",
        choices=["setup", "status", "remove", "gui"],
        help="Ação a ser executada: setup (cadastrar CLI), status (verificar), remove (remover), gui (interface gráfica)",
    )
    parser.add_argument(
        "--target",
        default=WindowsCredentialProvider.DEFAULT_TARGET_NAME,
        help="Nome do target no Windows Credential Manager (default: FinBot/Binance/Production)",
    )

    args = parser.parse_args(argv)
    provider = WindowsCredentialProvider(target_name=args.target)

    if args.action == "setup":
        return cli_setup(provider)
    elif args.action == "status":
        return cli_status(provider)
    elif args.action == "remove":
        return cli_remove(provider)
    elif args.action == "gui":
        from finbot.credentials_gui import run_gui
        return run_gui(provider=provider)
    return 0


if __name__ == "__main__":
    sys.exit(main())
