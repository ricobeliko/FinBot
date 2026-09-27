"""Módulo de cálculo de métricas de performance e carteira para o FinBot (FASE 7).

Funções puras desacopladas de componentes de UI.
Recebem dados e retornam estruturas tipadas e determinísticas.
Zero chamadas de rede ou IO.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from finbot.storage import PaperAccount, PaperPosition, PaperTrade


@dataclass(frozen=True)
class PerformanceMetrics:
    """Métricas de performance histórica e operacional consolidadas."""

    total_trades: int
    closed_trades: int
    winning_trades: int
    losing_trades: int
    break_even_trades: int
    win_rate_pct: float
    total_realized_pnl: Decimal
    total_fees: Decimal
    best_trade_pnl: Decimal | None
    worst_trade_pnl: Decimal | None


def calculate_performance_metrics(trades: list[PaperTrade]) -> PerformanceMetrics:
    """Calcula estatísticas de desempenho histórico sobre lista de trades simulados.

    Garante integridade matemática com zero trades (evita divisão por zero).
    """
    total_trades = len(trades)
    closed_trades_list = [t for t in trades if t.side == "SELL" and t.realized_pnl is not None]
    closed_count = len(closed_trades_list)

    total_fees = sum((t.fee for t in trades), Decimal("0.00"))
    total_realized_pnl = sum((t.realized_pnl for t in closed_trades_list), Decimal("0.00"))

    if closed_count == 0:
        return PerformanceMetrics(
            total_trades=total_trades,
            closed_trades=0,
            winning_trades=0,
            losing_trades=0,
            break_even_trades=0,
            win_rate_pct=0.0,
            total_realized_pnl=Decimal("0.00"),
            total_fees=total_fees,
            best_trade_pnl=None,
            worst_trade_pnl=None,
        )

    winning_trades = 0
    losing_trades = 0
    break_even_trades = 0
    best_pnl: Decimal | None = None
    worst_pnl: Decimal | None = None

    for t in closed_trades_list:
        pnl = t.realized_pnl
        assert pnl is not None
        if pnl > Decimal("0.00"):
            winning_trades += 1
        elif pnl < Decimal("0.00"):
            losing_trades += 1
        else:
            break_even_trades += 1

        if best_pnl is None or pnl > best_pnl:
            best_pnl = pnl
        if worst_pnl is None or pnl < worst_pnl:
            worst_pnl = pnl

    win_rate_pct = round((winning_trades / closed_count) * 100.0, 2)

    return PerformanceMetrics(
        total_trades=total_trades,
        closed_trades=closed_count,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        break_even_trades=break_even_trades,
        win_rate_pct=win_rate_pct,
        total_realized_pnl=total_realized_pnl,
        total_fees=total_fees,
        best_trade_pnl=best_pnl,
        worst_trade_pnl=worst_pnl,
    )


def calculate_paper_equity(
    account: PaperAccount,
    position: PaperPosition,
    current_price: Decimal | None = None,
) -> Decimal:
    """Calcula o valor patrimonial total aproximado da conta (USDT + valor a mercado de BTC).

    Se não houver preço atual informado ou não houver posição, equity = saldo USDT.
    """
    if position.side == "LONG" and position.quantity > Decimal("0") and current_price is not None:
        gross_btc_value = (position.quantity * current_price).quantize(Decimal("0.01"))
        return account.usdt_balance + gross_btc_value
    return account.usdt_balance


def calculate_unrealized_pnl(
    position: PaperPosition,
    current_price: Decimal | None,
) -> tuple[Decimal, float] | None:
    """Calcula o P/L não realizado (em USDT e %) da posição Spot LONG aberta.

    Retorna (unrealized_usdt, unrealized_pct) ou None se não houver posição ou preço.
    """
    if (
        position.side == "LONG"
        and position.quantity > Decimal("0")
        and position.cost_basis > Decimal("0")
        and current_price is not None
        and current_price > Decimal("0")
    ):
        current_gross = position.quantity * current_price
        unrealized_usdt = (current_gross - position.cost_basis).quantize(Decimal("0.01"))
        unrealized_pct = round(float((unrealized_usdt / position.cost_basis) * Decimal("100")), 2)
        return unrealized_usdt, unrealized_pct

    return None


def get_cumulative_pnl_series(trades: list[PaperTrade]) -> list[dict[str, Any]]:
    """Gera série histórica cronológica de P/L realizado acumulado por trade fechado.

    Utilizado para construção do gráfico de evolução patrimonial real sem dados artificiais.
    """
    closed_trades = [t for t in trades if t.side == "SELL" and t.realized_pnl is not None]
    # Inverte para ordem cronológica crescente (antigo para recente)
    closed_trades_chrono = list(reversed(closed_trades))

    series: list[dict[str, Any]] = []
    cumulative = Decimal("0.00")

    for i, t in enumerate(closed_trades_chrono, start=1):
        assert t.realized_pnl is not None
        cumulative += t.realized_pnl
        series.append(
            {
                "trade_seq": i,
                "trade_id": t.id,
                "timestamp": t.timestamp,
                "realized_pnl": float(t.realized_pnl),
                "cumulative_pnl": float(cumulative),
                "exit_reason": t.exit_reason or "MANUAL/UNKNOWN",
            }
        )

    return series


def calculate_runner_freshness(
    last_cycle_iso: str | None,
    current_time_iso: str | None = None,
    threshold_seconds: int = 180,
) -> tuple[str, float | None]:
    """Calcula o estado de frescor da execução do Paper Runner.

    Retorna:
    - ("RECENT", elapsed_seconds) se elapsed <= threshold_seconds (padrão 180s = 3min)
    - ("STALE", elapsed_seconds) se elapsed > threshold_seconds
    - ("UNKNOWN", None) se last_cycle_iso for nulo, vazio ou inválido
    """
    if not last_cycle_iso:
        return "UNKNOWN", None

    try:
        last_dt = datetime.fromisoformat(last_cycle_iso)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
    except Exception:
        return "UNKNOWN", None

    try:
        if current_time_iso:
            now_dt = datetime.fromisoformat(current_time_iso)
            if now_dt.tzinfo is None:
                now_dt = now_dt.replace(tzinfo=timezone.utc)
        else:
            now_dt = datetime.now(timezone.utc)
    except Exception:
        now_dt = datetime.now(timezone.utc)

    elapsed_seconds = max(0.0, (now_dt - last_dt).total_seconds())

    if elapsed_seconds <= threshold_seconds:
        return "RECENT", elapsed_seconds
    return "STALE", elapsed_seconds
