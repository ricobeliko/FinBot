"""Adapter dedicado e hermeticamente isolado para Binance Spot Testnet (FASE 8.4C2).

Fornece integração com a Binance Spot Testnet oficial (https://testnet.binance.vision)
para validação segura do pipeline de ordens sem risco financeiro.

REGRAS DE SEGURANÇA E ISOLAMENTO:
1. PRODUÇÃO NUNCA É TOCADA: O adapter é estritamente restrito à Testnet.
2. SENTRY DEFENSIVO: Antes de qualquer chamada de ESCRITA (create/cancel), valida que o
   endpoint CCXT aponta exclusivamente para `testnet.binance.vision` e JAMAIS para `api.binance.com`.
3. ATIVAÇÃO CCXT SANDBOX: `set_sandbox_mode(True)` é chamado IMEDIATAMENTE após a criação da
   instância CCXT, antes de qualquer requisição de rede, conforme orientação oficial do CCXT.
4. CREDENCIAIS SEPARADAS: Provedor de credenciais consome exclusivamente o target
   `FinBot/Binance/SpotTestnet` no Windows Credential Manager ou fake provider em testes.
   Credenciais de produção NUNCA são utilizadas.
5. ARMAMENTO EXPLÍCITO: Escritas exigem `testnet_execution_enabled == True`.
   Default seguro: `False` (FAIL-CLOSED).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import logging
from typing import Any

import ccxt

from finbot.config import BinanceEnvironment
from finbot.credentials import (
    BinanceCredentials,
    CredentialProvider,
    CredentialsMissingError,
    WindowsCredentialProvider,
)
from finbot.live_executor import (
    AmbiguousExecutionError,
    ExchangeOrderResult,
    OrderStatus,
)

logger = logging.getLogger(__name__)

TESTNET_HOST_KEYWORD: str = "testnet.binance.vision"
PRODUCTION_HOST_KEYWORD: str = "api.binance.com"


class TestnetSentryError(RuntimeError):
    """Lançado quando o sentry defensivo detecta endpoint ou ambiente inconsistente."""


class TestnetExecutionNotArmedError(RuntimeError):
    """Lançado quando uma operação de escrita é solicitada sem armamento da Testnet."""


def verify_testnet_endpoint(client: Any) -> None:
    """Sentry defensivo fail-closed: verifica se o client CCXT aponta estritamente para a Testnet.

    Se houver qualquer divergência, ausência de endpoint ou vestígio de produção:
    a operação é categoricamente rejeitada.
    """
    if client is None:
        raise TestnetSentryError("Sentry Check: Client CCXT não inicializado.")

    urls = getattr(client, "urls", {})
    if not isinstance(urls, dict):
        raise TestnetSentryError("Sentry Check: Estrutura de URLs inválida no client CCXT.")

    api_urls = urls.get("api", {})
    if not isinstance(api_urls, dict):
        raise TestnetSentryError("Sentry Check: Estrutura api_urls ausente no client CCXT.")

    public_url = str(api_urls.get("public", ""))
    private_url = str(api_urls.get("private", ""))

    # 1. NUNCA pode conter o endpoint de Produção (Prioridade máxima de isolamento)
    if PRODUCTION_HOST_KEYWORD in public_url or PRODUCTION_HOST_KEYWORD in private_url:
        raise TestnetSentryError(
            f"Sentry Check Falhou: Endpoint de PRODUÇÃO detectado ({PRODUCTION_HOST_KEYWORD})! "
            f"public='{public_url}', private='{private_url}'. Operação bloqueada imediatamente."
        )

    # 2. Deve conter obrigatoriamente o domínio da Testnet
    if TESTNET_HOST_KEYWORD not in public_url or TESTNET_HOST_KEYWORD not in private_url:
        raise TestnetSentryError(
            f"Sentry Check Falhou: URLs CCXT não apontam para a Binance Testnet ({TESTNET_HOST_KEYWORD}). "
            f"public='{public_url}', private='{private_url}'."
        )


def map_binance_status_to_order_status(raw_status: str | None) -> OrderStatus:
    """Mapeia o status retornado pela Binance/CCXT para o OrderStatus determinístico."""
    if not raw_status:
        return OrderStatus.UNKNOWN

    st = str(raw_status).strip().upper()
    mapping = {
        "NEW": OrderStatus.ACKNOWLEDGED,
        "OPEN": OrderStatus.ACKNOWLEDGED,
        "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
        "FILLED": OrderStatus.FILLED,
        "CLOSED": OrderStatus.FILLED,
        "CANCELED": OrderStatus.CANCELED,
        "CANCELLED": OrderStatus.CANCELED,
        "PENDING_CANCEL": OrderStatus.CANCEL_PENDING,
        "REJECTED": OrderStatus.REJECTED,
        "EXPIRED": OrderStatus.REJECTED,
        "EXPIRED_IN_MATCH": OrderStatus.REJECTED,
    }
    return mapping.get(st, OrderStatus.UNKNOWN)


class BinanceSpotTestnetOrderAdapter:
    """Adapter para execução de ordens na Binance Spot Testnet oficial.

    Implementa o protocolo `ExchangeOrderAdapter` com sentry defensivo e armamento estrito.
    """

    def __init__(
        self,
        credential_provider: CredentialProvider | None = None,
        client: Any | None = None,
        testnet_execution_enabled: bool = False,
    ) -> None:
        self.credential_provider = credential_provider or WindowsCredentialProvider.for_environment(
            BinanceEnvironment.SPOT_TESTNET
        )
        self.testnet_execution_enabled = testnet_execution_enabled
        self.environment: BinanceEnvironment = BinanceEnvironment.SPOT_TESTNET
        self._client = client

    def _get_client(self) -> Any:
        """Inicializa e autentica o cliente CCXT configurado para Spot Testnet."""
        if self._client is not None:
            return self._client

        if not self.credential_provider.has_binance_credentials():
            raise CredentialsMissingError(
                "Credenciais da Binance Spot Testnet ausentes. "
                "Cadastre as chaves de Testnet via CLI ou GUI no target FinBot/Binance/SpotTestnet."
            )

        creds: BinanceCredentials = self.credential_provider.get_binance_credentials()

        exchange = ccxt.binance(
            {
                "apiKey": creds.api_key,
                "secret": creds.api_secret,
                "enableRateLimit": True,
                "options": {
                    "defaultType": "spot",
                    "adjustForTimeDifference": True,
                },
            }
        )

        # CCXT Sandbox Activation — OBRIGATÓRIO imediatamente após instanciação
        exchange.set_sandbox_mode(True)

        # Sentry check imediato
        verify_testnet_endpoint(exchange)

        self._client = exchange
        return self._client

    def _assert_write_allowed(self) -> None:
        """Verifica defesas mandatórias antes de qualquer mutação na exchange."""
        if not self.testnet_execution_enabled:
            raise TestnetExecutionNotArmedError(
                "Operação de escrita na Binance Spot Testnet desarmada por padrão. "
                "Exige testnet_execution_enabled=True."
            )

        client = self._get_client()
        verify_testnet_endpoint(client)

    # =========================================================================
    # LEITURA / METADADOS (READ-ONLY)
    # =========================================================================

    def get_account_status(self) -> dict[str, Any]:
        """Consulta o status da conta na Spot Testnet."""
        client = self._get_client()
        verify_testnet_endpoint(client)
        try:
            return client.fetch_status()
        except Exception:
            # Fallback para consulta de conta direta
            try:
                return client.private_get_account()
            except Exception as exc:
                raise RuntimeError(f"Erro ao consultar status na Testnet: {exc}") from exc

    def get_balances(self) -> dict[str, dict[str, Decimal]]:
        """Consulta saldos livres e totais da conta Spot Testnet."""
        client = self._get_client()
        verify_testnet_endpoint(client)
        raw_bal = client.fetch_balance()
        balances: dict[str, dict[str, Decimal]] = {}
        for asset, data in raw_bal.get("total", {}).items():
            tot = Decimal(str(data))
            if tot > 0:
                free_val = Decimal(str(raw_bal.get("free", {}).get(asset, 0)))
                used_val = Decimal(str(raw_bal.get("used", {}).get(asset, 0)))
                balances[asset] = {
                    "free": free_val,
                    "used": used_val,
                    "total": tot,
                }
        return balances

    def load_markets(self) -> dict[str, Any]:
        """Carrega metadados e filtros de mercado da Spot Testnet."""
        client = self._get_client()
        verify_testnet_endpoint(client)
        return client.load_markets()

    def fetch_ticker(self, symbol: str) -> dict[str, Any]:
        """Consulta o ticker atual do mercado na Spot Testnet."""
        client = self._get_client()
        verify_testnet_endpoint(client)
        return client.fetch_ticker(symbol)

    def fetch_order(
        self, symbol: str, order_id: str | None, client_order_id: str | None
    ) -> ExchangeOrderResult | None:
        """Consulta o estado atual de uma ordem na Spot Testnet."""
        client = self._get_client()
        verify_testnet_endpoint(client)

        params: dict[str, Any] = {}
        if client_order_id:
            params["origClientOrderId"] = client_order_id

        try:
            order_data = client.fetch_order(id=order_id, symbol=symbol, params=params)
        except Exception as exc:
            logger.warning(
                "Falha ao consultar ordem na Testnet (order_id=%s, client_order_id=%s): %s",
                order_id,
                client_order_id,
                exc,
            )
            return None

        if not order_data:
            return None

        return self._build_order_result(order_data, fallback_client_id=client_order_id or "")

    # =========================================================================
    # ESCRITA (WRITE / MUTATION)
    # =========================================================================

    def submit_order(self, payload: dict[str, Any]) -> ExchangeOrderResult:
        """Submete uma ordem à Binance Spot Testnet."""
        self._assert_write_allowed()
        client = self._get_client()

        symbol = payload["symbol"]
        order_type = payload["type"]
        side = payload["side"]
        amount = payload["amount"]
        price = payload.get("price")
        params = dict(payload.get("params", {}))

        # Garante parâmetro de clientOrderId canônico
        client_order_id = params.get("clientOrderId") or ""

        try:
            raw_res = client.create_order(
                symbol=symbol,
                type=order_type,
                side=side,
                amount=amount,
                price=price,
                params=params,
            )
            return self._build_order_result(raw_res, fallback_client_id=client_order_id)
        except (TimeoutError, ccxt.RequestTimeout, ccxt.NetworkError) as exc:
            # Falha de rede ou timeout: exige reconciliação determinística por clientOrderId
            logger.error(
                "Timeout/falha de rede ao submeter ordem na Testnet (clientOrderId=%s): %s",
                client_order_id,
                exc,
            )
            raise AmbiguousExecutionError(
                f"Timeout ao submeter ordem na Binance Spot Testnet: {exc}"
            ) from exc
        except Exception as exc:
            logger.error("Erro na API da Testnet ao submeter ordem: %s", exc)
            raise

    def cancel_order(
        self, symbol: str, order_id: str | None, client_order_id: str | None
    ) -> ExchangeOrderResult:
        """Cancela uma ordem existente na Spot Testnet."""
        self._assert_write_allowed()
        client = self._get_client()

        params: dict[str, Any] = {}
        if client_order_id:
            params["origClientOrderId"] = client_order_id

        try:
            raw_res = client.cancel_order(
                id=order_id,
                symbol=symbol,
                params=params,
            )
            return self._build_order_result(raw_res, fallback_client_id=client_order_id or "")
        except Exception as exc:
            logger.error("Erro ao cancelar ordem na Testnet: %s", exc)
            raise

    def _build_order_result(
        self, raw: dict[str, Any], fallback_client_id: str = ""
    ) -> ExchangeOrderResult:
        """Constrói ExchangeOrderResult a partir do retorno da API CCXT / Binance."""
        info = raw.get("info", {}) if isinstance(raw.get("info"), dict) else {}
        cid = (
            raw.get("clientOrderId")
            or info.get("clientOrderId")
            or fallback_client_id
            or "unknown"
        )
        raw_status = info.get("status") or raw.get("status")
        status = map_binance_status_to_order_status(raw_status)

        exch_id = str(raw.get("id") or info.get("orderId") or "")
        symbol = str(raw.get("symbol") or info.get("symbol") or "")
        side = str(raw.get("side") or info.get("side") or "").upper()
        order_type = str(raw.get("type") or info.get("type") or "").upper()

        req_qty = Decimal(str(raw.get("amount") or info.get("origQty") or "0"))
        exec_qty = Decimal(str(raw.get("filled") or info.get("executedQty") or "0"))
        cum_quote = Decimal(str(raw.get("cost") or info.get("cummulativeQuoteQty") or "0"))

        limit_price_raw = raw.get("price") or info.get("price")
        limit_price: Decimal | None = None
        if limit_price_raw is not None:
            try:
                lp = Decimal(str(limit_price_raw))
                if lp > Decimal("0"):
                    limit_price = lp
            except Exception:
                limit_price = None

        avg_price_raw = raw.get("average")
        avg_price: Decimal | None = None
        if exec_qty > Decimal("0"):
            if avg_price_raw is not None:
                try:
                    ap = Decimal(str(avg_price_raw))
                    if ap > Decimal("0"):
                        avg_price = ap
                except Exception:
                    pass
            if avg_price is None and cum_quote > Decimal("0"):
                avg_price = cum_quote / exec_qty
        else:
            avg_price = None

        fee_val: Decimal | None = None
        fee_asset: str | None = None
        fee_data = raw.get("fee")
        if isinstance(fee_data, dict):
            cost = fee_data.get("cost")
            if cost is not None:
                fee_val = Decimal(str(cost))
            fee_asset = fee_data.get("currency")

        now_iso = datetime.now(timezone.utc).isoformat()
        created_at = (
            datetime.fromtimestamp(raw["timestamp"] / 1000, tz=timezone.utc).isoformat()
            if raw.get("timestamp")
            else now_iso
        )

        return ExchangeOrderResult(
            client_order_id=cid,
            exchange_order_id=exch_id or None,
            status=status,
            symbol=symbol,
            side=side,
            order_type=order_type,
            requested_quantity=req_qty,
            executed_quantity=exec_qty,
            cumulative_quote_quantity=cum_quote,
            average_price=avg_price,
            fee=fee_val,
            fee_asset=fee_asset,
            limit_price=limit_price,
            requested_price=limit_price,
            created_at=created_at,
            updated_at=now_iso,
            raw_response=raw,
        )
