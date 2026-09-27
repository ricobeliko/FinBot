"""Módulo de Adaptive Paper Trading com Shadow Mode e Fallback Seguro (FASE 7.9I).

Implementa a infraestrutura para que modelos de pesquisa devidamente validados (VALIDATED)
possam acompanhar ou influenciar o Paper Trading sem alterar destrutivamente o bot:
1. Três modos operacionais: OFF (default), SHADOW e ADAPTIVE.
2. Verificação estrita de governança: Somente modelos com status VALIDATED no ModelRegistry
   são autorizados a emitir previsões. Candidatos (CANDIDATE), rejeitados (REJECTED) e
   revogados (REVOKED) são bloqueados de forma fail-closed.
3. Validação de integridade e fingerprints de features e target antes de qualquer inferência.
4. Shadow Mode: Avalia o modelo, gera predições e registra divergências, mas preserva 100%
   o sinal da estratégia existente (final_signal = existing_signal).
5. Adaptive Mode: Recomendações adaptativas conduzem o sinal apenas se houver modelo VALIDATED.
   Qualquer anomalia (erro de inferência, NaN, Inf, falha de modelo) ativa FALLBACK imediato
   para a estratégia existente.
6. Soberania do Risk Engine: Todas as decisões operacionais passam obrigatoriamente pelas regras
   de risco (Stop Loss, Limite de Posição, Cooldown, Kill Switch, Daily Loss). O modelo NUNCA
   tem poder de veto sobre o Risk Engine.
7. Persistência de predições e auditoria na tabela 'adaptive_predictions'.

REGRAS ARQUITETURAIS:
- NUNCA conectar o modelo à Binance privada ou a chaves de API.
- Zero ordens reais.
- O Paper Runner com ADAPTIVE_MODE='off' deve manter comportamento 100% idêntico ao original.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import logging
import math
from pathlib import Path
from typing import Any, Sequence

from finbot.config import Config
from finbot.exchange import CandleData
from finbot.lab.learning import FEATURE_NAMES, FORBIDDEN_OUTCOME_FIELDS
from finbot.lab.model_registry import (
    STATUS_CANDIDATE,
    STATUS_REJECTED,
    STATUS_REVOKED,
    STATUS_VALIDATED,
    ModelManifest,
    ModelRegistry,
    compute_feature_fingerprint,
    compute_target_fingerprint,
)
from finbot.storage import PaperAccount, PaperPosition, PaperStorage
from finbot.strategy import Signal

logger = logging.getLogger(__name__)

# Modos suportados
MODE_OFF = "off"
MODE_SHADOW = "shadow"
MODE_ADAPTIVE = "adaptive"

VALID_MODES = {MODE_OFF, MODE_SHADOW, MODE_ADAPTIVE}

# Recomendações adaptativas
REC_LONG_BIAS = "LONG_BIAS"
REC_NO_LONG_BIAS = "NO_LONG_BIAS"


@dataclass(frozen=True)
class AdaptivePredictionRecord:
    """Registro determinístico de predição e auditoria para o dataset Shadow/Adaptive."""

    prediction_id: str
    timestamp: str
    candle_timestamp: int
    symbol: str
    timeframe: str
    model_id: str | None
    model_status: str
    feature_fingerprint: str | None
    target_name: str | None
    prediction: float | None
    prediction_valid: bool
    mode: str
    existing_signal: str
    adaptive_recommendation: str | None
    adaptive_signal: str | None
    final_signal: str
    is_disagreement: bool
    risk_decision: str | None = None
    risk_reason: str | None = None
    fallback_reason: str | None = None
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if not d["created_at"]:
            d["created_at"] = datetime.now(timezone.utc).isoformat()
        return d


@dataclass(frozen=True)
class AdaptiveCycleResult:
    """Resultado do ciclo de avaliação adaptativa."""

    mode: str
    final_signal: Signal
    decision_reason: str
    adaptive_recommendation: str | None
    adaptive_signal: Signal | None
    record: AdaptivePredictionRecord | None
    is_fallback: bool
    fallback_reason: str | None


def load_validated_model(
    model_id: str,
    registry_db: str | Path | None = None,
) -> tuple[ModelManifest | None, str | None]:
    """Carrega um modelo do Registry garantindo que está com status VALIDATED e íntegro.

    Retorna (manifest, None) em caso de sucesso.
    Em qualquer falha (fail-closed), retorna (None, motivo_do_bloqueio).
    """
    if not model_id or not model_id.strip():
        return None, "NO_MODEL_CONFIGURED"

    db_path = registry_db or "data/lab/results/model_registry/model_registry.sqlite3"
    try:
        registry = ModelRegistry(db_path=db_path)
        model = registry.get_model(model_id.strip())
    except Exception as exc:
        logger.error("Falha ao acessar Model Registry (%s): %s", db_path, exc)
        return None, f"REGISTRY_ACCESS_ERROR: {exc}"

    if model is None:
        return None, "MODEL_NOT_FOUND"

    # Verificação estrita de status: SOMENTE VALIDATED PODE OPERAR
    if model.status == STATUS_REJECTED:
        return None, "MODEL_REJECTED"
    if model.status == STATUS_CANDIDATE:
        return None, "MODEL_NOT_VALIDATED"
    if model.status == STATUS_REVOKED:
        return None, "MODEL_REVOKED"
    if model.status != STATUS_VALIDATED:
        return None, f"MODEL_STATUS_{model.status}"

    # Verificação de integridade dos fingerprints
    expected_feat_fp = compute_feature_fingerprint(model.feature_names, model.feature_set_version)
    if model.feature_fingerprint != expected_feat_fp:
        return None, "MODEL_INTEGRITY_FAILURE_FEATURE_FINGERPRINT"

    expected_tgt_fp = compute_target_fingerprint(model.target_name, model.target_definition)
    if model.target_fingerprint != expected_tgt_fp:
        return None, "MODEL_INTEGRITY_FAILURE_TARGET_FINGERPRINT"

    return model, None


def build_decision_features(
    closed_candles: Sequence[CandleData],
    short_window: int = 5,
    long_window: int = 10,
    now_iso: str | None = None,
) -> dict[str, float]:
    """Extrai features puras e decision-safe no instante do fechamento do último candle."""
    if len(closed_candles) < long_window:
        raise ValueError(
            f"Candles insuficientes para cálculo de features: {len(closed_candles)}/{long_window}"
        )

    last_c = closed_candles[-1]
    closes = [c.close for c in closed_candles]

    sma_s = sum(closes[-short_window:]) / short_window
    sma_l = sum(closes[-long_window:]) / long_window
    sma_dist = sma_s - sma_l
    sma_rat = (sma_s / sma_l) if sma_l > 0 else 1.0

    if now_iso:
        dt = datetime.fromisoformat(now_iso)
    else:
        dt = datetime.fromtimestamp(last_c.timestamp / 1000, tz=timezone.utc)

    feats = {
        "price": float(last_c.close),
        "open": float(last_c.open),
        "high": float(last_c.high),
        "low": float(last_c.low),
        "close": float(last_c.close),
        "volume": float(last_c.volume),
        "short_window": float(short_window),
        "long_window": float(long_window),
        "sma_short": float(sma_s),
        "sma_long": float(sma_l),
        "sma_distance": float(sma_dist),
        "sma_ratio": float(sma_rat),
        "hour": float(dt.hour),
        "day_of_week": float(dt.weekday()),
    }

    # Blindagem de segurança: verifica que nenhuma feature proibida está presente
    for fname in feats:
        if fname in FORBIDDEN_OUTCOME_FIELDS:
            raise ValueError(f"Violação grave de leakage detectada: {fname}")

    return feats


def predict(model: ModelManifest, features: dict[str, float]) -> float:
    """Calcula a inferência do modelo com base nos coeficientes salvos no manifesto ou parâmetros."""
    coefs: dict[str, float] = {}
    intercept: float = 0.0

    # 1. Tenta carregar coeficientes de model_parameters
    if "coefficients" in model.model_parameters:
        coefs = model.model_parameters["coefficients"]
        intercept = float(model.model_parameters.get("intercept", 0.0))
    elif "learning_results" in model.artifact_paths:
        p = Path(model.artifact_paths["learning_results"])
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
                coefs = data.get("coefficients", {})
                intercept = float(data.get("intercept", 0.0))

    if not coefs:
        # Fallback genérico para fixtures sintéticas de teste
        raise ValueError("Coeficientes do modelo não encontrados no manifesto ou artefatos.")

    # Inferência linear: y_hat = sum(w_i * x_i) + b
    y_hat = intercept
    for fname, w in coefs.items():
        if fname in features:
            y_hat += w * features[fname]

    if math.isnan(y_hat) or math.isinf(y_hat):
        raise ValueError(f"Predição inválida produzida pelo modelo: {y_hat}")

    return float(y_hat)


def evaluate_adaptive_cycle(
    config: Config,
    closed_candles: Sequence[CandleData],
    latest_closed: CandleData,
    existing_signal: Signal,
    existing_reason: str,
    position: PaperPosition,
    account: PaperAccount,
    storage: PaperStorage | None = None,
    now_iso: str | None = None,
) -> AdaptiveCycleResult:
    """Executa a camada adaptativa em modo OFF, SHADOW ou ADAPTIVE com fallback seguro."""
    mode = getattr(config, "adaptive_mode", MODE_OFF).lower()
    if mode not in VALID_MODES:
        logger.warning("Modo adaptativo desconhecido '%s'. Usando 'off'.", mode)
        mode = MODE_OFF

    # 1. Modo OFF: desativado, retorna imediatamente
    if mode == MODE_OFF:
        return AdaptiveCycleResult(
            mode=MODE_OFF,
            final_signal=existing_signal,
            decision_reason=existing_reason,
            adaptive_recommendation=None,
            adaptive_signal=None,
            record=None,
            is_fallback=False,
            fallback_reason=None,
        )

    model_id = getattr(config, "adaptive_model_id", "").strip()
    registry_db = getattr(config, "adaptive_registry_db", None)
    now_dt = now_iso or datetime.now(timezone.utc).isoformat()
    pred_id = f"pred_{latest_closed.timestamp}_{model_id[:8] if model_id else 'nomodel'}"

    # 2. Carrega modelo do Registry (garante status VALIDATED)
    model, load_error = load_validated_model(model_id, registry_db=registry_db)

    if load_error is not None:
        logger.info("Adaptive Paper: Modelo não autorizado (%s). Fallback ativo.", load_error)
        rec = AdaptivePredictionRecord(
            prediction_id=pred_id,
            timestamp=now_dt,
            candle_timestamp=latest_closed.timestamp,
            symbol=config.symbol,
            timeframe=config.paper_timeframe,
            model_id=model_id or None,
            model_status=load_error,
            feature_fingerprint=None,
            target_name=None,
            prediction=None,
            prediction_valid=False,
            mode=mode,
            existing_signal=existing_signal.value,
            adaptive_recommendation=None,
            adaptive_signal=None,
            final_signal=existing_signal.value,
            is_disagreement=False,
            fallback_reason=load_error,
            created_at=now_dt,
        )
        if storage is not None:
            storage.record_adaptive_prediction(rec.to_dict())

        return AdaptiveCycleResult(
            mode=mode,
            final_signal=existing_signal,
            decision_reason=f"FALLBACK ({load_error}): {existing_reason}",
            adaptive_recommendation=None,
            adaptive_signal=None,
            record=rec,
            is_fallback=True,
            fallback_reason=load_error,
        )

    # 3. Extrai features e executa inferência
    assert model is not None
    try:
        features = build_decision_features(
            closed_candles=closed_candles,
            short_window=config.short_window,
            long_window=config.long_window,
            now_iso=now_dt,
        )
        pred_value = predict(model, features)
        pred_valid = True
        inf_error = None
    except Exception as exc:
        logger.warning("Falha na inferência adaptativa do modelo '%s': %s", model_id, exc)
        pred_value = None
        pred_valid = False
        inf_error = f"PREDICTION_ERROR: {exc}"

    if not pred_valid or pred_value is None:
        # Fallback por falha de inferência
        rec = AdaptivePredictionRecord(
            prediction_id=pred_id,
            timestamp=now_dt,
            candle_timestamp=latest_closed.timestamp,
            symbol=config.symbol,
            timeframe=config.paper_timeframe,
            model_id=model.model_id,
            model_status=model.status,
            feature_fingerprint=model.feature_fingerprint,
            target_name=model.target_name,
            prediction=None,
            prediction_valid=False,
            mode=mode,
            existing_signal=existing_signal.value,
            adaptive_recommendation=None,
            adaptive_signal=None,
            final_signal=existing_signal.value,
            is_disagreement=False,
            fallback_reason=inf_error,
            created_at=now_dt,
        )
        if storage is not None:
            storage.record_adaptive_prediction(rec.to_dict())

        return AdaptiveCycleResult(
            mode=mode,
            final_signal=existing_signal,
            decision_reason=f"FALLBACK ({inf_error}): {existing_reason}",
            adaptive_recommendation=None,
            adaptive_signal=None,
            record=rec,
            is_fallback=True,
            fallback_reason=inf_error,
        )

    # 4. Regra Simples de Recomendação Adaptativa:
    # prediction > 0 -> LONG_BIAS
    # prediction <= 0 -> NO_LONG_BIAS
    if pred_value > 0.0:
        recommendation = REC_LONG_BIAS
        if position.side == "NONE":
            adaptive_signal = Signal.BUY
        else:
            adaptive_signal = Signal.HOLD
    else:
        recommendation = REC_NO_LONG_BIAS
        if position.side == "LONG":
            adaptive_signal = Signal.SELL
        else:
            adaptive_signal = Signal.HOLD

    is_disagreement = (adaptive_signal.value != existing_signal.value)

    # 5. Aplicação conforme o Modo
    if mode == MODE_SHADOW:
        # Shadow: O modelo observa e emite recomendação, mas final_signal é ESTRITAMENTE o sinal existente
        final_signal = existing_signal
        decision_reason = (
            f"SHADOW ({recommendation}, pred={pred_value:+.6f}, "
            f"disagree={is_disagreement}): {existing_reason}"
        )
    elif mode == MODE_ADAPTIVE:
        # Adaptive: O modelo sugere o sinal, sujeito à aprovação estrita do Risk Engine
        final_signal = adaptive_signal
        decision_reason = (
            f"ADAPTIVE ({recommendation}, pred={pred_value:+.6f}): "
            f"Sinal adaptativo {adaptive_signal.value} gerado."
        )
    else:
        final_signal = existing_signal
        decision_reason = existing_reason

    rec = AdaptivePredictionRecord(
        prediction_id=pred_id,
        timestamp=now_dt,
        candle_timestamp=latest_closed.timestamp,
        symbol=config.symbol,
        timeframe=config.paper_timeframe,
        model_id=model.model_id,
        model_status=model.status,
        feature_fingerprint=model.feature_fingerprint,
        target_name=model.target_name,
        prediction=pred_value,
        prediction_valid=True,
        mode=mode,
        existing_signal=existing_signal.value,
        adaptive_recommendation=recommendation,
        adaptive_signal=adaptive_signal.value,
        final_signal=final_signal.value,
        is_disagreement=is_disagreement,
        fallback_reason=None,
        created_at=now_dt,
    )
    if storage is not None:
        storage.record_adaptive_prediction(rec.to_dict())

    return AdaptiveCycleResult(
        mode=mode,
        final_signal=final_signal,
        decision_reason=decision_reason,
        adaptive_recommendation=recommendation,
        adaptive_signal=adaptive_signal,
        record=rec,
        is_fallback=False,
        fallback_reason=None,
    )
