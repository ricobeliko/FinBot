"""Motor determinístico de controle e gestão de risco (FASE 6).

Este módulo atua como barreira obrigatória entre a estratégia e a execução de ordens simuladas.
Nenhum trade (BUY ou SELL) pode ser executado sem autorização explícita do Risk Engine.

REGRAS ARQUITETURAIS:
- 100% Determinístico e Local-first.
- NÃO importa CCXT nem realiza chamadas de rede ou IO.
- Avalia stop loss defensivo, limite de perda diária, cooldown por candles fechados,
  kill switch e tamanho máximo de posição.
- Sells para redução ou encerramento de risco NUNCA são bloqueados por perda diária,
  cooldown ou kill switch.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum

from finbot.config import Config
from finbot.storage import PaperAccount, PaperPosition, PaperTrade
from finbot.strategy import Signal


class RiskDecisionCode(str, Enum):
    """Códigos padronizados de decisão do Risk Engine."""

    ALLOWED = "ALLOWED"
    DEFENSIVE_EXIT_STOP_LOSS = "DEFENSIVE_EXIT_STOP_LOSS"
    HOLD = "HOLD"
    KILL_SWITCH_ACTIVE = "KILL_SWITCH_ACTIVE"
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    MAX_POSITION = "MAX_POSITION"
    COOLDOWN_ACTIVE = "COOLDOWN_ACTIVE"
    INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE"
    NO_POSITION_TO_CLOSE = "NO_POSITION_TO_CLOSE"


@dataclass(frozen=True)
class RiskDecision:
    """Resultado formal e imutável emitido pelo Risk Engine."""

    allowed: bool
    code: RiskDecisionCode
    reason: str
    action: str  # "BUY", "SELL", "HOLD"
    target_notional: Decimal | None = None
    exit_reason: str | None = None  # "STOP_LOSS", "STRATEGY_SIGNAL" ou None


def calculate_daily_realized_loss(trades: list[PaperTrade], date_utc: str | None = None) -> Decimal:
    """Calcula o P/L realizado consolidado no dia UTC especificado (ou data atual UTC).

    Retorna o valor somado de realized_pnl de todas as vendas fechadas do dia.
    Valores negativos representam prejuízo acumulado no dia.
    """
    if date_utc is None:
        date_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    daily_pnl = Decimal("0.00")
    for t in trades:
        if t.side == "SELL" and t.realized_pnl is not None:
            if t.timestamp.startswith(date_utc):
                daily_pnl += t.realized_pnl

    return daily_pnl


def is_cooldown_active(
    last_closed_trade_candle_ts: int | None,
    current_candle_ts: int,
    cooldown_candles: int,
    timeframe_ms: int,
) -> bool:
    """Verifica se o período de cooldown após encerramento de posição ainda está ativo.

    Baseado estritamente em candles fechados (zero timers/sleep).
    Se uma posição foi encerrada no candle T_close, novos BUYs permanecem bloqueados
    durante os próximos 'cooldown_candles' fechados.
    """
    if last_closed_trade_candle_ts is None or cooldown_candles <= 0:
        return False

    elapsed_ms = current_candle_ts - last_closed_trade_candle_ts
    cooldown_required_ms = cooldown_candles * timeframe_ms
    return elapsed_ms <= cooldown_required_ms


class RiskEngine:
    """Motor de validação e controle de risco determinístico."""

    def __init__(self, config: Config) -> None:
        self.config = config

    def evaluate(
        self,
        account: PaperAccount,
        position: PaperPosition,
        signal: Signal,
        signal_reason: str,
        current_price: Decimal,
        candle_timestamp: int,
        timeframe_ms: int,
        kill_switch_active: bool,
        daily_realized_pnl: Decimal,
        last_closed_trade_candle_ts: int | None,
    ) -> RiskDecision:
        """Avalia determinística e sequencialmente a intenção operacional segundo regras de risco.

        PRECEDÊNCIA CONCEITUAL OBRIGATÓRIA:
        1. Proteção de Risco / Stop Loss Defensivo (se houver posição aberta e preço violar limite)
        2. Sinal SELL da Estratégia (saída solicitada para encerrar posição existente)
        3. Sinal HOLD da Estratégia (sem intenção de trade financeiro)
        4. Sinal BUY da Estratégia (sujeito à esteira completa de validações de risco)
        5. Sinal SELL sem posição aberta (ignorado)
        """
        # =====================================================================
        # 1. PROTEÇÃO DE RISCO / STOP LOSS DEFENSIVO
        # =====================================================================
        if position.side == "LONG" and position.quantity > Decimal("0"):
            entry_price = position.entry_price
            if entry_price > Decimal("0"):
                loss_ratio = (entry_price - current_price) / entry_price
                stop_loss_threshold = Decimal(str(self.config.risk_stop_loss_pct))
                if loss_ratio >= stop_loss_threshold:
                    loss_pct = loss_ratio * Decimal("100")
                    threshold_pct = stop_loss_threshold * Decimal("100")
                    return RiskDecision(
                        allowed=True,
                        code=RiskDecisionCode.DEFENSIVE_EXIT_STOP_LOSS,
                        reason=(
                            f"Stop loss defensivo ativado: desvalorização de {loss_pct:.2f}% "
                            f"atingiu ou superou o limite de {threshold_pct:.2f}%."
                        ),
                        action="SELL",
                        target_notional=None,
                        exit_reason="STOP_LOSS",
                    )

        # =====================================================================
        # 2. SINAL SELL DA ESTRATÉGIA
        # =====================================================================
        if signal == Signal.SELL:
            if position.side == "LONG" and position.quantity > Decimal("0"):
                # Proteções NUNCA bloqueiam encerramento de posição
                return RiskDecision(
                    allowed=True,
                    code=RiskDecisionCode.ALLOWED,
                    reason=f"SELL autorizado por sinal da estratégia ({signal_reason}).",
                    action="SELL",
                    target_notional=None,
                    exit_reason="STRATEGY_SIGNAL",
                )
            return RiskDecision(
                allowed=False,
                code=RiskDecisionCode.NO_POSITION_TO_CLOSE,
                reason="SELL ignorado: nenhuma posição aberta para encerrar.",
                action="HOLD",
                target_notional=None,
                exit_reason=None,
            )

        # =====================================================================
        # 3. SINAL HOLD DA ESTRATÉGIA
        # =====================================================================
        if signal == Signal.HOLD:
            return RiskDecision(
                allowed=True,
                code=RiskDecisionCode.HOLD,
                reason=f"HOLD: {signal_reason}",
                action="HOLD",
                target_notional=None,
                exit_reason=None,
            )

        # =====================================================================
        # 4. SINAL BUY DA ESTRATÉGIA — GATES DE RISCO
        # =====================================================================
        if signal == Signal.BUY:
            # Gate 4.1: Posição já aberta (Max Position: 1 posição spot simultânea)
            if position.side == "LONG" and position.quantity > Decimal("0"):
                return RiskDecision(
                    allowed=False,
                    code=RiskDecisionCode.MAX_POSITION,
                    reason="BUY ignorado: posição já aberta (limite de 1 posição simultânea / max position atingido).",
                    action="HOLD",
                    target_notional=None,
                    exit_reason=None,
                )

            # Gate 4.2: Kill Switch Ativo
            if kill_switch_active:
                return RiskDecision(
                    allowed=False,
                    code=RiskDecisionCode.KILL_SWITCH_ACTIVE,
                    reason="BUY bloqueado: Kill Switch ativado pelo operador.",
                    action="HOLD",
                    target_notional=None,
                    exit_reason=None,
                )

            # Gate 4.3: Limite de Perda Diária Realizada (Daily Loss Limit)
            max_daily_loss = Decimal(str(self.config.risk_max_daily_loss))
            if daily_realized_pnl <= -max_daily_loss:
                return RiskDecision(
                    allowed=False,
                    code=RiskDecisionCode.DAILY_LOSS_LIMIT,
                    reason=(
                        f"BUY bloqueado: perda diária realizada atingiu o limite "
                        f"({daily_realized_pnl:.2f} <= -{max_daily_loss:.2f} USDT)."
                    ),
                    action="HOLD",
                    target_notional=None,
                    exit_reason=None,
                )

            # Gate 4.4: Cooldown após encerramento de posição anterior
            if is_cooldown_active(
                last_closed_trade_candle_ts=last_closed_trade_candle_ts,
                current_candle_ts=candle_timestamp,
                cooldown_candles=self.config.risk_cooldown_candles,
                timeframe_ms=timeframe_ms,
            ):
                return RiskDecision(
                    allowed=False,
                    code=RiskDecisionCode.COOLDOWN_ACTIVE,
                    reason=(
                        f"BUY bloqueado: cooldown ativo após encerramento recente de posição "
                        f"({self.config.risk_cooldown_candles} candle(s) de intervalo exigido)."
                    ),
                    action="HOLD",
                    target_notional=None,
                    exit_reason=None,
                )

            # Gate 4.5: Limite de Notional da Posição (Max Position Notional)
            trade_notional = Decimal(str(self.config.paper_trade_notional))
            max_position_notional = Decimal(str(self.config.risk_max_position_notional))
            if trade_notional > max_position_notional:
                return RiskDecision(
                    allowed=False,
                    code=RiskDecisionCode.MAX_POSITION,
                    reason=(
                        f"BUY bloqueado: notional da operação ({trade_notional:.2f} USDT) "
                        f"excede o limite de posição ({max_position_notional:.2f} USDT)."
                    ),
                    action="HOLD",
                    target_notional=None,
                    exit_reason=None,
                )

            # Gate 4.6: Saldo Disponível Suficiente (Notional + Taxa de Entrada)
            commission_rate = Decimal(str(self.config.paper_commission))
            fee = (trade_notional * commission_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            total_required = trade_notional + fee
            if account.usdt_balance < total_required:
                return RiskDecision(
                    allowed=False,
                    code=RiskDecisionCode.INSUFFICIENT_BALANCE,
                    reason=(
                        f"BUY bloqueado: saldo USDT insuficiente "
                        f"({account.usdt_balance:.2f} < {total_required:.2f} USDT)."
                    ),
                    action="HOLD",
                    target_notional=None,
                    exit_reason=None,
                )

            # Todos os gates de risco foram satisfeitos
            return RiskDecision(
                allowed=True,
                code=RiskDecisionCode.ALLOWED,
                reason=f"BUY autorizado pelo Risk Engine ({signal_reason}).",
                action="BUY",
                target_notional=trade_notional,
                exit_reason=None,
            )

        # Fallback genérico para sinal não reconhecido
        return RiskDecision(
            allowed=False,
            code=RiskDecisionCode.HOLD,
            reason=f"Sinal não reconhecido ou sem ação: {signal}",
            action="HOLD",
            target_notional=None,
            exit_reason=None,
        )
