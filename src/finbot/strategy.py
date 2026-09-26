"""Motor de estratégia determinístico do FinBot para a FASE 3 (Strategy Engine).

Calcula sinais puramente matemáticos (BUY, SELL, HOLD) com base em dados históricos.
NÃO emite ordens, NÃO se comunica com exchanges e NÃO executa trades.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Sequence


class Signal(str, Enum):
    """Sinais operacionais produzidos pela estratégia."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass(frozen=True)
class StrategyResult:
    """Resultado detalhado da avaliação da estratégia."""

    signal: Signal
    short_ma: float | None
    long_ma: float | None
    prev_short_ma: float | None
    prev_long_ma: float | None
    reason: str


def _calculate_sma(prices: Sequence[float]) -> float:
    """Calcula a média móvel simples de uma sequência de preços."""
    return sum(prices) / len(prices)


def evaluate_sma_crossover(
    data: Sequence[Any],
    short_window: int = 5,
    long_window: int = 10,
) -> StrategyResult:
    """Avalia o evento de cruzamento de médias móveis simples (SMA).

    Parâmetros:
    - data: Sequência de candles (com atributo 'close') ou sequência numérica de preços de fechamento.
    - short_window: Período da média móvel curta (ex: 5).
    - long_window: Período da média móvel longa (ex: 10).

    Regras de sinal:
    - BUY:  Média curta cruza de baixo para cima da média longa (prev_short <= prev_long e curr_short > curr_long).
    - SELL: Média curta cruza de cima para baixo da média longa (prev_short >= prev_long e curr_short < curr_long).
    - HOLD: Nenhum cruzamento recente identificado ou dados insuficientes.
    """
    if short_window <= 0:
        raise ValueError(f"short_window deve ser maior que 0, recebido: {short_window}")
    if long_window <= short_window:
        raise ValueError(
            f"long_window ({long_window}) deve ser estritamente maior que short_window ({short_window})"
        )

    # Extrai lista de fechamentos (suporta float direto ou objetos com atributo close)
    closes: list[float] = [
        float(item.close) if hasattr(item, "close") else float(item)
        for item in data
    ]

    required_candles = long_window + 1
    if len(closes) < required_candles:
        return StrategyResult(
            signal=Signal.HOLD,
            short_ma=None,
            long_ma=None,
            prev_short_ma=None,
            prev_long_ma=None,
            reason=(
                f"Dados insuficientes: {len(closes)} candles fornecidos, "
                f"necessário pelo menos {required_candles} para detectar cruzamento."
            ),
        )

    # Janelas no candle anterior (t-1)
    prev_short_prices = closes[-short_window - 1 : -1]
    prev_long_prices = closes[-long_window - 1 : -1]
    prev_short_ma = _calculate_sma(prev_short_prices)
    prev_long_ma = _calculate_sma(prev_long_prices)

    # Janelas no candle atual (t)
    curr_short_prices = closes[-short_window:]
    curr_long_prices = closes[-long_window:]
    curr_short_ma = _calculate_sma(curr_short_prices)
    curr_long_ma = _calculate_sma(curr_long_prices)

    # Detecção de evento de cruzamento
    if prev_short_ma <= prev_long_ma and curr_short_ma > curr_long_ma:
        signal = Signal.BUY
        reason = "SMA curta cruzou acima da SMA longa (BUY crossover)"
    elif prev_short_ma >= prev_long_ma and curr_short_ma < curr_long_ma:
        signal = Signal.SELL
        reason = "SMA curta cruzou abaixo da SMA longa (SELL crossover)"
    else:
        signal = Signal.HOLD
        reason = "no crossover detected"

    return StrategyResult(
        signal=signal,
        short_ma=curr_short_ma,
        long_ma=curr_long_ma,
        prev_short_ma=prev_short_ma,
        prev_long_ma=prev_long_ma,
        reason=reason,
    )
