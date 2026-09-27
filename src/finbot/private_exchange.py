"""Módulo de integração privada com a Binance (FASE 8.1).

Fornece interface isolada, segura e estritamente READ-ONLY para consulta de informações
de conta e saldos na Binance.

REGRAS DE SEGURANÇA:
1. NUNCA enviar ordens reais (trading desabilitado nesta fase).
2. NUNCA expor API key ou API secret em logs, exceções ou representações de string.
3. FAIL-CLOSED: Qualquer erro de credencial, rede, autenticação ou rate-limit interrompe
   a operação de forma segura, sem fallback silencioso para trading.
4. MODO PAPER ISOLADO: Nenhuma chamada privada é efetuada no modo paper.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import logging
from typing import Any

import ccxt

from finbot.config import Config
from finbot.credentials import (
    BinanceCredentials,
    CredentialProvider,
    CredentialsMissingError as _BaseCredentialsMissingError,
    WindowsCredentialProvider,
)

logger = logging.getLogger(__name__)


# =============================================================================
# EXCEÇÕES DE SEGURANÇA E OPERAÇÃO PRIVADA (FAIL-CLOSED)
# =============================================================================

class PrivateExchangeError(Exception):
    """Exceção base para erros na integração privada com a exchange."""


class CredentialsMissingError(_BaseCredentialsMissingError, PrivateExchangeError):
    """Lançada quando a API Key ou o API Secret estão ausentes ou vazios."""


class AuthenticationError(PrivateExchangeError):
    """Lançada quando a autenticação na exchange falha (chaves inválidas, IP não autorizado, etc.)."""


class NetworkError(PrivateExchangeError):
    """Lançada quando ocorrem falhas de conexão, rede, DNS ou timeout."""


class RateLimitError(PrivateExchangeError):
    """Lançada quando a exchange retorna erro de limite de requisições excedido."""


class InvalidConfigurationError(PrivateExchangeError):
    """Lançada quando a configuração operacional viola as restrições da camada privada."""


class LiveTradingBlockedError(PrivateExchangeError):
    """Lançada caso qualquer método de envio/alteração/cancelamento de ordem seja invocado."""


# =============================================================================
# HIGIENIZAÇÃO DE SECRETS E LOGS
# =============================================================================

def sanitize_secret_text(text: str, secrets: list[str]) -> str:
    """Substitui ocorrências de credenciais por [REDACTED], impedindo vazamentos em logs/erros."""
    if not text:
        return ""
    sanitized = text
    for secret in secrets:
        if secret and len(secret) >= 4:
            sanitized = sanitized.replace(secret, "[REDACTED]")
    return sanitized


# =============================================================================
# ESTRUTURAS DE DADOS (READ-ONLY)
# =============================================================================

@dataclass(frozen=True)
class BalanceData:
    """Saldo auditado de um ativo específico (com precisão Decimal)."""

    asset: str
    free: Decimal
    locked: Decimal
    total: Decimal


@dataclass(frozen=True)
class AccountStatus:
    """Status de permissões e tipo da conta na Binance."""

    account_type: str
    can_trade: bool
    can_withdraw: bool
    can_deposit: bool
    buyer_commission: int | None = None
    seller_commission: int | None = None
    update_time: int | None = None


@dataclass(frozen=True)
class AccountSnapshot:
    """Representação normalizada e consolidada do estado da conta na Binance."""

    account_status: AccountStatus
    can_trade: bool
    can_withdraw: bool
    can_deposit: bool
    balances: dict[str, BalanceData]
    fetched_at: str
    source: str = "binance_private"


# =============================================================================
# CLIENTE PRIVADO BINANCE (ESTRITAMENTE READ-ONLY)
# =============================================================================

class BinancePrivateExchange:
    """Cliente isolado para operações privadas (READ-ONLY) na Binance via CCXT.

    Todas as chamadas operam sob princípio Fail-Closed e mascaramento estrito de secrets.
    As credenciais são obtidas exclusivamente via CredentialProvider (Windows Credential Manager).
    """

    def __init__(
        self,
        config: Config,
        credential_provider: CredentialProvider | None = None,
        client: ccxt.Exchange | Any | None = None,
    ) -> None:
        # 1. Barreira contra modo paper / modos não live
        if config.trading_mode != "live":
            raise InvalidConfigurationError(
                f"Cliente privado não pode ser instanciado no modo '{config.trading_mode}'. "
                "Requer explicitamente trading_mode='live'."
            )

        # 2. Obtenção segura de credenciais exclusivamente via CredentialProvider (Fail-Closed)
        if credential_provider is None:
            credential_provider = WindowsCredentialProvider()

        self._credential_provider = credential_provider

        try:
            creds = self._credential_provider.get_binance_credentials()
        except _BaseCredentialsMissingError as exc:
            logger.error("Credential provider: %s", self._credential_provider.get_provider_name())
            logger.error("Credential status: MISSING")
            raise CredentialsMissingError(str(exc)) from None
        except Exception as exc:
            logger.error("Credential provider: %s", self._credential_provider.get_provider_name())
            logger.error("Credential status: MISSING (erro: %s)", exc)
            raise CredentialsMissingError(f"Falha ao obter credenciais da Binance: {exc}") from None

        if not creds or not creds.api_key.strip() or not creds.api_secret.strip():
            logger.error("Credential provider: %s", self._credential_provider.get_provider_name())
            logger.error("Credential status: MISSING (credenciais vazias)")
            raise CredentialsMissingError(
                f"Credenciais da Binance não configuradas ou vazias no {self._credential_provider.get_provider_name()}."
            )

        self._api_key = creds.api_key.strip()
        self._api_secret = creds.api_secret.strip()
        self.config = config

        logger.info("Credential provider: %s", self._credential_provider.get_provider_name())
        logger.info("Credential status: PRESENT")

        # 3. Inicialização do CCXT (ou injeção de mock)
        if client is not None:
            self._client = client
        else:
            try:
                self._client = ccxt.binance({
                    "apiKey": self._api_key,
                    "secret": self._api_secret,
                    "enableRateLimit": True,
                    "options": {
                        "defaultType": "spot",
                        "adjustForTimeDifference": True,
                    },
                })
            except Exception as exc:
                sanitized_msg = self._sanitize(str(exc))
                raise PrivateExchangeError(f"Falha ao instanciar CCXT Binance: {sanitized_msg}") from None

    @property
    def credential_provider(self) -> CredentialProvider:
        """Retorna o provedor de credenciais associado."""
        return self._credential_provider

    def __repr__(self) -> str:
        """Representação segura que NUNCA expõe chaves ou segredos."""
        return f"BinancePrivateExchange(mode={self.config.trading_mode}, provider={self._credential_provider.get_provider_name()}, authenticated=True)"

    def __str__(self) -> str:
        return self.__repr__()

    def _sanitize(self, message: str) -> str:
        """Remove secrets da mensagem."""
        return sanitize_secret_text(message, [self._api_key, self._api_secret])

    def close(self) -> None:
        """Encerra recursos de conexão se aplicável."""
        if hasattr(self._client, "close"):
            try:
                self._client.close()
            except Exception:
                pass

    def get_account_status(self) -> AccountStatus:
        """Consulta permissões e status operacional da conta."""
        try:
            raw_balance = self._client.fetch_balance()
            if not isinstance(raw_balance, dict):
                raise PrivateExchangeError("Resposta malformada da exchange ao consultar status da conta.")

            info = raw_balance.get("info", {})
            if not isinstance(info, dict):
                info = {}

            can_trade = bool(info.get("canTrade", False))
            can_withdraw = bool(info.get("canWithdraw", False))
            can_deposit = bool(info.get("canDeposit", False))
            account_type = str(info.get("accountType", "SPOT"))
            buyer_commission = int(info["buyerCommission"]) if "buyerCommission" in info and info["buyerCommission"] is not None else None
            seller_commission = int(info["sellerCommission"]) if "sellerCommission" in info and info["sellerCommission"] is not None else None
            update_time = int(info["updateTime"]) if "updateTime" in info and info["updateTime"] is not None else None

            logger.info("Status da conta consultado com sucesso. Tipo: %s, canTrade: %s.", account_type, can_trade)

            return AccountStatus(
                account_type=account_type,
                can_trade=can_trade,
                can_withdraw=can_withdraw,
                can_deposit=can_deposit,
                buyer_commission=buyer_commission,
                seller_commission=seller_commission,
                update_time=update_time,
            )
        except ccxt.AuthenticationError as exc:
            msg = self._sanitize(str(exc))
            logger.error("Falha de autenticação na Binance: %s", msg)
            raise AuthenticationError(f"Falha de autenticação na Binance: {msg}") from None
        except ccxt.RateLimitExceeded as exc:
            msg = self._sanitize(str(exc))
            logger.error("Limite de requisições excedido na Binance: %s", msg)
            raise RateLimitError(f"Rate limit excedido na Binance: {msg}") from None
        except (ccxt.NetworkError, ccxt.RequestTimeout, ccxt.ExchangeNotAvailable) as exc:
            msg = self._sanitize(str(exc))
            logger.error("Erro de rede/timeout ao consultar conta na Binance: %s", msg)
            raise NetworkError(f"Erro de rede ao consultar Binance: {msg}") from None
        except PrivateExchangeError:
            raise
        except Exception as exc:
            msg = self._sanitize(str(exc))
            logger.error("Erro inesperado na exchange privada: %s", msg)
            raise PrivateExchangeError(f"Erro na exchange privada: {msg}") from None

    def get_balances(self, non_zero_only: bool = True) -> dict[str, BalanceData]:
        """Consulta os saldos de todos os ativos da conta Spot."""
        try:
            raw_balance = self._client.fetch_balance()
            if not isinstance(raw_balance, dict):
                raise PrivateExchangeError("Resposta malformada da exchange ao consultar saldos.")

            balances: dict[str, BalanceData] = {}

            total_dict = raw_balance.get("total")
            free_dict = raw_balance.get("free")
            used_dict = raw_balance.get("used")

            if not isinstance(total_dict, dict):
                total_dict = {}
            if not isinstance(free_dict, dict):
                free_dict = {}
            if not isinstance(used_dict, dict):
                used_dict = {}

            all_assets = set(total_dict.keys()) | set(free_dict.keys()) | set(used_dict.keys())

            for asset in sorted(all_assets):
                if not asset or not isinstance(asset, str):
                    continue
                if asset in ("info", "free", "used", "total"):
                    continue

                try:
                    free_raw = free_dict.get(asset, 0.0) or 0.0
                    used_raw = used_dict.get(asset, 0.0) or 0.0
                    free_val = Decimal(str(free_raw))
                    used_val = Decimal(str(used_raw))
                    total_raw = total_dict.get(asset)
                    total_val = Decimal(str(total_raw)) if total_raw is not None else (free_val + used_val)
                except Exception:
                    continue

                if non_zero_only and total_val == Decimal("0"):
                    continue

                balances[asset] = BalanceData(
                    asset=asset,
                    free=free_val,
                    locked=used_val,
                    total=total_val,
                )

            logger.info("Saldos consultados com sucesso (%d ativos retornados).", len(balances))
            return balances

        except ccxt.AuthenticationError as exc:
            msg = self._sanitize(str(exc))
            raise AuthenticationError(f"Falha de autenticação ao consultar saldos: {msg}") from None
        except ccxt.RateLimitExceeded as exc:
            msg = self._sanitize(str(exc))
            raise RateLimitError(f"Rate limit excedido ao consultar saldos: {msg}") from None
        except (ccxt.NetworkError, ccxt.RequestTimeout, ccxt.ExchangeNotAvailable) as exc:
            msg = self._sanitize(str(exc))
            raise NetworkError(f"Erro de rede ao consultar saldos: {msg}") from None
        except PrivateExchangeError:
            raise
        except Exception as exc:
            msg = self._sanitize(str(exc))
            raise PrivateExchangeError(f"Erro ao consultar saldos: {msg}") from None

    def get_balance(self, asset: str) -> BalanceData:
        """Consulta o saldo de um ativo específico."""
        if not asset or not isinstance(asset, str):
            raise ValueError("Identificador do ativo não pode ser vazio.")

        asset_norm = asset.strip().upper()
        balances = self.get_balances(non_zero_only=False)
        return balances.get(
            asset_norm,
            BalanceData(
                asset=asset_norm,
                free=Decimal("0"),
                locked=Decimal("0"),
                total=Decimal("0"),
            ),
        )

    def get_account_snapshot(self) -> AccountSnapshot:
        """Gera um snapshot normalizado completo do estado da conta.

        NOTA DE SEGURANÇA:
        can_trade reflete exclusivamente o status retornado pela Binance.
        O FinBot NÃO utiliza esse campo para autorizar ou executar ordens.
        """
        status = self.get_account_status()
        balances = self.get_balances(non_zero_only=True)
        now_iso = datetime.now(timezone.utc).isoformat()

        return AccountSnapshot(
            account_status=status,
            can_trade=status.can_trade,
            can_withdraw=status.can_withdraw,
            can_deposit=status.can_deposit,
            balances=balances,
            fetched_at=now_iso,
            source="binance_private",
        )

    # =========================================================================
    # BARREIRAS ARQUITETURAIS CONTRA ORDENS (FASE 8.1)
    # =========================================================================

    def create_order(self, *args: Any, **kwargs: Any) -> None:
        """Bloqueio arquitetural estrito: ordens reais são proibidas na Fase 8.1."""
        raise LiveTradingBlockedError(
            "CRITICAL: Criação de ordens reais bloqueada na FASE 8.1. Live trading não está habilitado."
        )

    def cancel_order(self, *args: Any, **kwargs: Any) -> None:
        """Bloqueio arquitetural estrito: cancelamento de ordens reais é proibido na Fase 8.1."""
        raise LiveTradingBlockedError(
            "CRITICAL: Cancelamento de ordens reais bloqueado na FASE 8.1. Live trading não está habilitado."
        )
