"""Módulo de extração de Features e cálculo de Labels do FinBot (FASE 7.9F).

Implementa a transformação determinística e offline de experiências em:
1. FeatureSet (Decision Time, FEATURE-SAFE): exclusivamente variáveis disponíveis até Close[t].
2. LabelSet (Outcome Time, OUTCOME-ONLY): retornos futuros medidos a partir da execução em Open[t+1]
   ao longo de horizontes de N candles (Close[t+N]), preservando estritamente NULL para dados insuficientes.

Semântica Temporal Oficial:
Candle[t] -> Decisão em Close[t] -> Execução em Open[t+1] -> Horizonte N em Close[t+N].
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Sequence

from finbot.experience import ExperienceRecord


def _parse_iso_utc(ts: str) -> datetime:
    """Converte string ISO8601 para datetime UTC timezone-aware."""
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _get_candle_attr(candle: Any, attr: str) -> Any:
    """Extrai atributo de objeto ou chave de dicionário de candle."""
    if hasattr(candle, attr):
        return getattr(candle, attr)
    if isinstance(candle, dict) and attr in candle:
        return candle[attr]
    return None


@dataclass(frozen=True)
class FeatureSet:
    """Conjunto de features determinísticas conhecidas em Decision Time (FEATURE-SAFE).

    Garantia anti-leakage: Sob nenhuma circunstância inclui campos de outcome ou retornos futuros.
    """

    # Provenance
    experience_id: str
    source: str
    source_id: str
    run_id: str
    decision_at: str
    candle_timestamp: int
    symbol: str
    timeframe: str

    # Grupo A — Mercado (Snapshot do candle fechado t e preço observado)
    price: float
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None

    # Grupo B — Estratégia e Indicadores
    short_window: int
    long_window: int
    sma_short: float | None
    sma_long: float | None
    sma_distance: float | None  # sma_short - sma_long
    sma_ratio: float | None  # sma_short / sma_long se sma_long != 0

    # Grupo C — Estado
    signal: str
    signal_reason: str
    position_before: str
    risk_decision: str
    risk_reason: str
    risk_allowed: bool

    # Grupo D — Contexto Temporal (UTC derivado exclusivamente de decision_at)
    hour: int  # 0..23
    day_of_week: int  # 0..6 (Segunda-feira = 0, Domingo = 6)

    def to_dict(self) -> dict[str, Any]:
        """Serializa o conjunto de features em dicionário plano."""
        return asdict(self)


@dataclass(frozen=True)
class LabelSet:
    """Conjunto de rótulos futuros conhecidos exclusivamente em Outcome Time (OUTCOME-ONLY).

    Garantia temporal: Mede retornos futuros a partir do preço de execução de entrada Open[t+1]
    até o fechamento do candle no horizonte t+N. Se o horizonte não estiver disponível no histórico,
    o valor permanece estritamente None (NULL), jamais 0 ou valores aproximados.
    """

    experience_id: str
    reference_price: float | None  # Preço de execução base (Open[t+1] ou execution_price)
    future_return_5: float | None  # Retorno percentual após 5 candles
    future_return_20: float | None  # Retorno percentual após 20 candles
    future_return_50: float | None  # Retorno percentual após 50 candles
    future_return_100: float | None  # Retorno percentual após 100 candles
    outcome: str | None  # Desfecho da operação se concluída ("WIN", "LOSS", "BREAK_EVEN", etc.)

    def to_dict(self) -> dict[str, Any]:
        """Serializa os labels em dicionário plano."""
        return asdict(self)


def extract_features(
    experience: ExperienceRecord,
    historical_candles: Sequence[Any] | None = None,
) -> FeatureSet:
    """Extrai features puras e decision-safe a partir de uma experiência.

    Garantia Anti-Leakage:
    - Se historical_candles for fornecido, filtra estritamente candles com timestamp <= candle_timestamp,
      eliminando qualquer possibilidade de vazamento de candles futuros.
    - Contexto temporal (hour, day_of_week) é calculado unicamente a partir de decision_at em UTC.
    - Nenhum dado de outcome ou retorno futuro é incluído no FeatureSet resultante.
    """
    dec = experience.decision
    dt = _parse_iso_utc(dec.decision_at)

    short_w = int(dec.strategy_parameters.get("short_window", 5))
    long_w = int(dec.strategy_parameters.get("long_window", 10))

    # Valores base de OHLCV do decision context
    open_val = dec.open
    high_val = dec.high
    low_val = dec.low
    close_val = dec.close
    volume_val = dec.volume

    sma_short: float | None = None
    sma_long: float | None = None
    sma_dist: float | None = None
    sma_ratio: float | None = None

    if historical_candles:
        # Blindagem anti-leakage: descarta qualquer candle posterior a candle_timestamp
        safe_candles = [
            c for c in historical_candles
            if _get_candle_attr(c, "timestamp") <= dec.candle_timestamp
        ]

        # Se OHLCV estiver ausente no decision context, recupera do último candle fechado seguro
        if safe_candles and (close_val is None or open_val is None):
            last_c = safe_candles[-1]
            if _get_candle_attr(last_c, "timestamp") == dec.candle_timestamp:
                open_val = float(_get_candle_attr(last_c, "open"))
                high_val = float(_get_candle_attr(last_c, "high"))
                low_val = float(_get_candle_attr(last_c, "low"))
                close_val = float(_get_candle_attr(last_c, "close"))
                vol = _get_candle_attr(last_c, "volume")
                volume_val = float(vol) if vol is not None else None

        closes = [float(_get_candle_attr(c, "close")) for c in safe_candles]
        if len(closes) >= short_w:
            sma_short = round(sum(closes[-short_w:]) / short_w, 6)
        if len(closes) >= long_w:
            sma_long = round(sum(closes[-long_w:]) / long_w, 6)

        if sma_short is not None and sma_long is not None:
            sma_dist = round(sma_short - sma_long, 6)
            sma_ratio = round(sma_short / sma_long, 6) if sma_long != 0.0 else None

    return FeatureSet(
        experience_id=experience.experience_id,
        source=experience.source,
        source_id=experience.source_id,
        run_id=experience.run_id,
        decision_at=dec.decision_at,
        candle_timestamp=dec.candle_timestamp,
        symbol=dec.symbol,
        timeframe=dec.timeframe,
        price=dec.price,
        open=open_val,
        high=high_val,
        low=low_val,
        close=close_val,
        volume=volume_val,
        short_window=short_w,
        long_window=long_w,
        sma_short=sma_short,
        sma_long=sma_long,
        sma_distance=sma_dist,
        sma_ratio=sma_ratio,
        signal=dec.signal,
        signal_reason=dec.signal_reason,
        position_before=dec.position_before,
        risk_decision=dec.risk_decision,
        risk_reason=dec.risk_reason,
        risk_allowed=dec.risk_allowed,
        hour=dt.hour,
        day_of_week=dt.weekday(),
    )


def build_labels(
    experience: ExperienceRecord,
    candles: Sequence[Any],
    horizons: Sequence[int] = (5, 20, 50, 100),
) -> LabelSet:
    """Calcula os labels de retorno futuro para uma experiência a partir de uma série de candles.

    Semântica Temporal Estrita:
    - Candle de decisão: candle com timestamp == experience.decision.candle_timestamp (índice t).
    - Execução: ocorre no candle subsequente t+1 no preço Open[t+1] (ou execution_price se já preenchido).
    - Horizonte N: fechamento do candle em t+N (Close[t+N]).
    - Fórmula: future_return_N = (Close[t+N] - ReferencePrice) / ReferencePrice
    - Tratamento de insuficiência: se t+N ultrapassar o tamanho da série, retorna estritamente None (NULL).
    """
    target_ts = experience.decision.candle_timestamp

    # Localiza o índice do candle de decisão t
    t_idx: int | None = None
    for idx, c in enumerate(candles):
        if _get_candle_attr(c, "timestamp") == target_ts:
            t_idx = idx
            break

    if t_idx is None:
        raise ValueError(
            f"Candle de decisão com timestamp {target_ts} não encontrado na lista de candles fornecida."
        )

    # Determina o preço de referência de entrada (Open do candle t+1 ou execution_price)
    ref_price: float | None = None
    if experience.decision.execution_price is not None and experience.decision.execution_price > 0:
        ref_price = float(experience.decision.execution_price)
    elif t_idx + 1 < len(candles):
        ref_price = float(_get_candle_attr(candles[t_idx + 1], "open"))

    # Se não houver preço de referência válido, todos os retornos futuros são None
    future_returns: dict[int, float | None] = {h: None for h in horizons}

    if ref_price is not None and ref_price > 0:
        for h in horizons:
            future_idx = t_idx + h
            if future_idx < len(candles):
                future_close = float(_get_candle_attr(candles[future_idx], "close"))
                future_returns[h] = round((future_close - ref_price) / ref_price, 8)
            else:
                future_returns[h] = None

    outcome_label = experience.outcome.outcome if experience.outcome else None

    return LabelSet(
        experience_id=experience.experience_id,
        reference_price=ref_price,
        future_return_5=future_returns.get(5),
        future_return_20=future_returns.get(20),
        future_return_50=future_returns.get(50),
        future_return_100=future_returns.get(100),
        outcome=outcome_label,
    )


def build_experience_features_and_labels(
    experience: ExperienceRecord,
    candles: Sequence[Any],
    horizons: Sequence[int] = (5, 20, 50, 100),
) -> tuple[FeatureSet, LabelSet]:
    """Constrói atomicamente o par (FeatureSet, LabelSet) para uma experiência respeitando o contrato temporal."""
    features = extract_features(experience, historical_candles=candles)
    labels = build_labels(experience, candles=candles, horizons=horizons)
    return features, labels


def build_feature_label_dataset(
    experiences: Sequence[ExperienceRecord],
    candles: Sequence[Any],
    horizons: Sequence[int] = (5, 20, 50, 100),
) -> list[dict[str, Any]]:
    """Constrói dataset tabular consolidado a partir de uma coleção de experiências e candles históricos."""
    dataset: list[dict[str, Any]] = []
    for exp in experiences:
        feats, labs = build_experience_features_and_labels(exp, candles, horizons)
        row = feats.to_dict()
        lab_dict = labs.to_dict()
        # Remove experience_id duplicado no merge
        lab_dict.pop("experience_id", None)
        row.update(lab_dict)
        dataset.append(row)
    return dataset


def export_features_labels_csv(
    dataset: Sequence[dict[str, Any]],
    filepath: str | Path,
) -> Path:
    """Exporta dataset de features e labels de forma determinística para CSV plano."""
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)

    if not dataset:
        with open(path, "w", newline="", encoding="utf-8") as f:
            f.write("")
        return path

    fieldnames = list(dataset[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in dataset:
            writer.writerow(row)

    return path


def export_features_labels_json(
    dataset: Sequence[dict[str, Any]],
    filepath: str | Path,
) -> Path:
    """Exporta dataset de features e labels de forma determinística para JSON estruturado."""
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(list(dataset), f, indent=2)

    return path
