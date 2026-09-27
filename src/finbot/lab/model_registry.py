"""Módulo de Model Validation e Model Registry do FinBot Lab (FASE 7.9H).

Implementa o sistema local, determinístico, auditável e append-oriented para:
1. Cálculo de fingerprints determinísticos (Dataset, Features, Target, Modelo).
2. Construção de Manifesto Canônico estruturado (ModelManifest).
3. Estados formais de ciclo de vida: CANDIDATE, VALIDATED, REJECTED, REVOKED.
4. Validation Gate rigoroso com auditoria de integridade, ausência de leakage e superioridade OOS vs baseline.
5. Registro persistente e imutável em SQLite com log de auditoria append-only.
6. Exportação de relatórios estruturados em data/lab/results/model_registry/.
7. CLI para operações de pesquisa local.

REGRAS ARQUITETURAIS:
- 100% offline e isolado no FinBot Lab (pesquisa-first).
- NUNCA conectar o Model Registry ao Paper Runner, Risk Engine ou Strategy Engine.
- O modelo registrado NÃO opera em tempo real e NÃO emite ordens financeiras.
- Zero dependências adicionadas ao ambiente de produção.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import sqlite3
import sys
from typing import Any, Sequence

from finbot.lab.learning import (
    FEATURE_NAMES,
    FORBIDDEN_OUTCOME_FIELDS,
    LearningExperimentResult,
)

logger = logging.getLogger(__name__)

# =============================================================================
# 1. CONSTANTES E ESTADOS DO REGISTRY
# =============================================================================

STATUS_CANDIDATE = "CANDIDATE"
STATUS_VALIDATED = "VALIDATED"
STATUS_REJECTED = "REJECTED"
STATUS_REVOKED = "REVOKED"

VALID_STATUSES = {
    STATUS_CANDIDATE,
    STATUS_VALIDATED,
    STATUS_REJECTED,
    STATUS_REVOKED,
}

CHECK_PASS = "PASS"
CHECK_FAIL = "FAIL"
CHECK_NOT_RUN = "NOT_RUN"


# =============================================================================
# 2. FINGERPRINTS DETERMINÍSTICOS
# =============================================================================

def compute_dataset_fingerprint(candles_or_data: Any) -> str:
    """Calcula fingerprint criptográfico determinístico (SHA-256) de um dataset.

    Sensível a timestamps, volume, preços de abertura/fechamento e quantidade de candles.
    """
    hasher = hashlib.sha256()

    if isinstance(candles_or_data, (str, Path)):
        p = Path(candles_or_data)
        if not p.exists():
            raise FileNotFoundError(f"Arquivo de dataset não encontrado para fingerprint: {p}")
        with open(p, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()

    if isinstance(candles_or_data, Sequence):
        # Lista de CandleData ou dicts
        records = []
        for c in candles_or_data:
            ts = getattr(c, "timestamp", None) or (c.get("timestamp") if isinstance(c, dict) else None)
            close = getattr(c, "close", None) or (c.get("close") if isinstance(c, dict) else None)
            vol = getattr(c, "volume", None) or (c.get("volume") if isinstance(c, dict) else None)
            records.append(f"{ts}:{close}:{vol}")
        raw = "|".join(records)
        hasher.update(raw.encode("utf-8"))
        return hasher.hexdigest()

    if isinstance(candles_or_data, dict):
        raw = json.dumps(candles_or_data, sort_keys=True)
        hasher.update(raw.encode("utf-8"))
        return hasher.hexdigest()

    raise TypeError(f"Tipo não suportado para cálculo de dataset fingerprint: {type(candles_or_data)}")


def compute_feature_fingerprint(feature_names: Sequence[str], version: str = "1.0.0") -> str:
    """Calcula fingerprint determinístico para a lista ordenada de features e versão.

    Sensível à ordem: ['price', 'close'] != ['close', 'price'].
    """
    hasher = hashlib.sha256()
    payload = {
        "version": version,
        "features": list(feature_names),
    }
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
    hasher.update(raw.encode("utf-8"))
    return hasher.hexdigest()


def compute_target_fingerprint(
    target_name: str,
    semantics: str = "(Close[t+20] - Open[t+1]) / Open[t+1]",
    horizon: int = 20,
    reference_price: str = "Open[t+1]",
) -> str:
    """Calcula fingerprint determinístico para a semântica do target."""
    hasher = hashlib.sha256()
    payload = {
        "target_name": target_name,
        "semantics": semantics,
        "horizon": horizon,
        "reference_price": reference_price,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    hasher.update(raw.encode("utf-8"))
    return hasher.hexdigest()


def compute_model_id(canonical_payload: dict[str, Any]) -> str:
    """Calcula o identificador determinístico (model_id) a partir do payload canônico."""
    # Extrai estritamente as propriedades que definem a identidade científica do modelo
    identity_dict = {
        "dataset_fingerprint": canonical_payload.get("dataset_fingerprint"),
        "source": canonical_payload.get("source"),
        "symbol": canonical_payload.get("symbol"),
        "timeframe": canonical_payload.get("timeframe"),
        "target_name": canonical_payload.get("target_name"),
        "target_fingerprint": canonical_payload.get("target_fingerprint"),
        "feature_fingerprint": canonical_payload.get("feature_fingerprint"),
        "model_type": canonical_payload.get("model_type"),
        "model_parameters": canonical_payload.get("model_parameters"),
        "preprocessing": canonical_payload.get("preprocessing"),
        "preprocessing_fit_train_only": canonical_payload.get("preprocessing_fit_train_only"),
        "shuffle": canonical_payload.get("shuffle"),
        "train_range": canonical_payload.get("train_range"),
        "val_range": canonical_payload.get("val_range"),
        "test_range": canonical_payload.get("test_range"),
        "train_samples": canonical_payload.get("train_samples"),
        "validation_samples": canonical_payload.get("validation_samples"),
        "test_samples": canonical_payload.get("test_samples"),
        "code_version": canonical_payload.get("code_version"),
    }
    raw = json.dumps(identity_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    full_sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"model_{full_sha[:16]}"


# =============================================================================
# 3. ESTRUTURAS DE EVIDÊNCIA E MANIFESTO
# =============================================================================

@dataclass(frozen=True)
class ValidationCheck:
    """Registro individual de um teste efetuado pelo Validation Gate."""

    name: str
    status: str  # "PASS", "FAIL", "NOT_RUN"
    details: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ValidationReport:
    """Relatório estruturado emitido pelo Validation Gate para um modelo candidato."""

    model_id: str
    verdict: str  # "VALIDATED" ou "REJECTED"
    validated_at: str
    checks: list[ValidationCheck]
    reason: str
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "verdict": self.verdict,
            "validated_at": self.validated_at,
            "checks": [c.to_dict() for c in self.checks],
            "reason": self.reason,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ValidationReport:
        checks = [
            ValidationCheck(
                name=c["name"],
                status=c["status"],
                details=c["details"],
            )
            for c in data.get("checks", [])
        ]
        return cls(
            model_id=data["model_id"],
            verdict=data["verdict"],
            validated_at=data["validated_at"],
            checks=checks,
            reason=data["reason"],
            summary=data["summary"],
        )


@dataclass(frozen=True)
class WalkForwardEvidence:
    """Evidência de validação via Walk-Forward Analysis (FASE 7.9C), quando disponível."""

    status: str = CHECK_NOT_RUN
    window_count: int = 0
    positive_windows: int = 0
    negative_windows: int = 0
    oos_metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RobustnessEvidence:
    """Evidência de análise de robustez e sensibilidade (FASE 7.9D), quando disponível."""

    fee_sensitivity: str = CHECK_NOT_RUN
    parameter_neighborhood: str = CHECK_NOT_RUN
    temporal_stress: str = CHECK_NOT_RUN
    concentration: str = CHECK_NOT_RUN
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ModelManifest:
    """Manifesto canônico estruturado que define a identidade completa de um modelo."""

    model_id: str
    created_at: str
    status: str  # CANDIDATE, VALIDATED, REJECTED, REVOKED
    status_reason: str
    dataset_id: str
    dataset_fingerprint: str
    source: str
    symbol: str
    timeframe: str
    target_name: str
    target_definition: str
    target_fingerprint: str
    feature_set_version: str
    feature_names: list[str]
    feature_fingerprint: str
    preprocessing: str
    preprocessing_version: str
    preprocessing_fit_train_only: bool
    shuffle: bool
    model_type: str
    model_parameters: dict[str, Any]
    train_range: tuple[str, str]
    val_range: tuple[str, str]
    test_range: tuple[str, str]
    train_samples: int
    validation_samples: int
    test_samples: int
    training_environment: dict[str, Any]
    code_version: str
    metrics_train: dict[str, Any]
    metrics_validation: dict[str, Any]
    metrics_test: dict[str, Any]
    baseline_metrics_train: dict[str, Any]
    baseline_metrics_validation: dict[str, Any]
    baseline_metrics_test: dict[str, Any]
    walk_forward_evidence: WalkForwardEvidence = field(default_factory=WalkForwardEvidence)
    robustness_evidence: RobustnessEvidence = field(default_factory=RobustnessEvidence)
    validation_report: ValidationReport | None = None
    artifact_paths: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        res = asdict(self)
        res["train_range"] = list(self.train_range)
        res["val_range"] = list(self.val_range)
        res["test_range"] = list(self.test_range)
        if self.validation_report is not None:
            res["validation_report"] = self.validation_report.to_dict()
        return res

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelManifest:
        val_rep = (
            ValidationReport.from_dict(data["validation_report"])
            if data.get("validation_report")
            else None
        )
        wf_ev = (
            WalkForwardEvidence(**data.get("walk_forward_evidence", {}))
            if data.get("walk_forward_evidence")
            else WalkForwardEvidence()
        )
        rob_ev = (
            RobustnessEvidence(**data.get("robustness_evidence", {}))
            if data.get("robustness_evidence")
            else RobustnessEvidence()
        )
        return cls(
            model_id=data["model_id"],
            created_at=data["created_at"],
            status=data["status"],
            status_reason=data.get("status_reason", ""),
            dataset_id=data["dataset_id"],
            dataset_fingerprint=data["dataset_fingerprint"],
            source=data["source"],
            symbol=data["symbol"],
            timeframe=data["timeframe"],
            target_name=data["target_name"],
            target_definition=data["target_definition"],
            target_fingerprint=data["target_fingerprint"],
            feature_set_version=data["feature_set_version"],
            feature_names=list(data["feature_names"]),
            feature_fingerprint=data["feature_fingerprint"],
            preprocessing=data["preprocessing"],
            preprocessing_version=data["preprocessing_version"],
            preprocessing_fit_train_only=data["preprocessing_fit_train_only"],
            shuffle=data["shuffle"],
            model_type=data["model_type"],
            model_parameters=dict(data["model_parameters"]),
            train_range=tuple(data["train_range"]),  # type: ignore[arg-type]
            val_range=tuple(data["val_range"]),      # type: ignore[arg-type]
            test_range=tuple(data["test_range"]),    # type: ignore[arg-type]
            train_samples=int(data["train_samples"]),
            validation_samples=int(data["validation_samples"]),
            test_samples=int(data["test_samples"]),
            training_environment=dict(data.get("training_environment", {})),
            code_version=data.get("code_version", "1.0.0"),
            metrics_train=dict(data.get("metrics_train", {})),
            metrics_validation=dict(data.get("metrics_validation", {})),
            metrics_test=dict(data.get("metrics_test", {})),
            baseline_metrics_train=dict(data.get("baseline_metrics_train", {})),
            baseline_metrics_validation=dict(data.get("baseline_metrics_validation", {})),
            baseline_metrics_test=dict(data.get("baseline_metrics_test", {})),
            walk_forward_evidence=wf_ev,
            robustness_evidence=rob_ev,
            validation_report=val_rep,
            artifact_paths=dict(data.get("artifact_paths", {})),
        )


def create_manifest_from_experiment(
    result: LearningExperimentResult,
    dataset_id: str,
    dataset_fingerprint: str,
    source: str = "canonical_backtest_10k",
    symbol: str = "BTC/USDT",
    timeframe: str = "5m",
    model_type: str = "Ridge",
    model_parameters: dict[str, Any] | None = None,
    preprocessing: str = "StandardScaler",
    preprocessing_version: str = "1.0.0",
    code_version: str = "1.0.0",
    artifact_paths: dict[str, str] | None = None,
) -> ModelManifest:
    """Gera um ModelManifest consistente e determinístico a partir de LearningExperimentResult."""
    if model_parameters is None:
        model_parameters = {"alpha": 1.0, "random_state": 42}

    feat_fp = compute_feature_fingerprint(result.feature_names, version="1.0.0")
    target_def = "(Close[t+20] - Open[t+1]) / Open[t+1]"
    target_fp = compute_target_fingerprint(result.target_name, semantics=target_def, horizon=20)

    payload_for_id = {
        "dataset_fingerprint": dataset_fingerprint,
        "source": source,
        "symbol": symbol,
        "timeframe": timeframe,
        "target_name": result.target_name,
        "target_fingerprint": target_fp,
        "feature_fingerprint": feat_fp,
        "model_type": model_type,
        "model_parameters": model_parameters,
        "preprocessing": preprocessing,
        "preprocessing_fit_train_only": True,
        "shuffle": False,
        "train_range": list(result.train_range),
        "val_range": list(result.val_range),
        "test_range": list(result.test_range),
        "train_samples": result.n_train,
        "validation_samples": result.n_val,
        "test_samples": result.n_test,
        "code_version": code_version,
    }
    model_id = compute_model_id(payload_for_id)
    now_iso = datetime.now(timezone.utc).isoformat()

    return ModelManifest(
        model_id=model_id,
        created_at=now_iso,
        status=STATUS_CANDIDATE,
        status_reason="Registered as candidate for validation gate.",
        dataset_id=dataset_id,
        dataset_fingerprint=dataset_fingerprint,
        source=source,
        symbol=symbol,
        timeframe=timeframe,
        target_name=result.target_name,
        target_definition=target_def,
        target_fingerprint=target_fp,
        feature_set_version="1.0.0",
        feature_names=list(result.feature_names),
        feature_fingerprint=feat_fp,
        preprocessing=preprocessing,
        preprocessing_version=preprocessing_version,
        preprocessing_fit_train_only=True,
        shuffle=False,
        model_type=model_type,
        model_parameters=dict(model_parameters),
        train_range=result.train_range,
        val_range=result.val_range,
        test_range=result.test_range,
        train_samples=result.n_train,
        validation_samples=result.n_val,
        test_samples=result.n_test,
        training_environment={"python": sys.version.split()[0], "platform": sys.platform},
        code_version=code_version,
        metrics_train=result.model_train_metrics.to_dict(),
        metrics_validation=result.model_val_metrics.to_dict(),
        metrics_test=result.model_test_metrics.to_dict(),
        baseline_metrics_train=result.baseline_train_metrics.to_dict(),
        baseline_metrics_validation=result.baseline_val_metrics.to_dict(),
        baseline_metrics_test=result.baseline_test_metrics.to_dict(),
        walk_forward_evidence=WalkForwardEvidence(),
        robustness_evidence=RobustnessEvidence(),
        validation_report=None,
        artifact_paths=dict(artifact_paths or {}),
    )


# =============================================================================
# 4. VALIDATION GATE
# =============================================================================

def validate_model_candidate(
    manifest: ModelManifest,
    expected_dataset_fingerprint: str | None = None,
) -> tuple[str, ValidationReport]:
    """Valida um candidato formalmente com base em integridade, temporalidade e OOS.

    Retorna (new_status, validation_report).
    O veredito só é VALIDATED se TODOS os critérios de integridade passarem E
    o modelo demonstrar superioridade out-of-sample contra o baseline.
    Caso contrário, o veredito é REJECTED.
    """
    checks: list[ValidationCheck] = []
    now_iso = datetime.now(timezone.utc).isoformat()
    rejection_reasons: list[str] = []

    # 1. Checagem de integridade do Dataset Fingerprint
    if expected_dataset_fingerprint is not None:
        if manifest.dataset_fingerprint != expected_dataset_fingerprint:
            checks.append(ValidationCheck(
                name="CHECK_DATASET_INTEGRITY",
                status=CHECK_FAIL,
                details=(
                    f"Dataset fingerprint mismatch: registrado '{manifest.dataset_fingerprint}' "
                    f"!= atual '{expected_dataset_fingerprint}'"
                ),
            ))
            rejection_reasons.append("DATASET_FINGERPRINT_MISMATCH")
        else:
            checks.append(ValidationCheck(
                name="CHECK_DATASET_INTEGRITY",
                status=CHECK_PASS,
                details="Dataset fingerprint verificado com sucesso contra a fonte atual.",
            ))
    else:
        if not manifest.dataset_fingerprint or len(manifest.dataset_fingerprint) != 64:
            checks.append(ValidationCheck(
                name="CHECK_DATASET_INTEGRITY",
                status=CHECK_FAIL,
                details="Dataset fingerprint inválido no manifesto.",
            ))
            rejection_reasons.append("INVALID_DATASET_FINGERPRINT")
        else:
            checks.append(ValidationCheck(
                name="CHECK_DATASET_INTEGRITY",
                status=CHECK_PASS,
                details="Dataset fingerprint estruturalmente válido.",
            ))

    # 2. Checagem de integridade das Features
    expected_feat_fp = compute_feature_fingerprint(manifest.feature_names, manifest.feature_set_version)
    forbidden_used = [f for f in manifest.feature_names if f in FORBIDDEN_OUTCOME_FIELDS]
    if forbidden_used:
        checks.append(ValidationCheck(
            name="CHECK_FEATURE_INTEGRITY",
            status=CHECK_FAIL,
            details=f"Violação grave de leakage: campos de outcome usados como features: {forbidden_used}",
        ))
        rejection_reasons.append("FORBIDDEN_OUTCOME_FEATURES_DETECTED")
    elif manifest.feature_fingerprint != expected_feat_fp:
        checks.append(ValidationCheck(
            name="CHECK_FEATURE_INTEGRITY",
            status=CHECK_FAIL,
            details=(
                f"Feature fingerprint mismatch: manifesto '{manifest.feature_fingerprint}' "
                f"!= calculado '{expected_feat_fp}'"
            ),
        ))
        rejection_reasons.append("FEATURE_FINGERPRINT_MISMATCH")
    else:
        checks.append(ValidationCheck(
            name="CHECK_FEATURE_INTEGRITY",
            status=CHECK_PASS,
            details=f"Features ({len(manifest.feature_names)}) auditadas e em conformidade sem leakage.",
        ))

    # 3. Checagem de integridade do Target
    expected_tgt_fp = compute_target_fingerprint(manifest.target_name, manifest.target_definition)
    if manifest.target_fingerprint != expected_tgt_fp:
        checks.append(ValidationCheck(
            name="CHECK_TARGET_INTEGRITY",
            status=CHECK_FAIL,
            details=(
                f"Target fingerprint mismatch: manifesto '{manifest.target_fingerprint}' "
                f"!= calculado '{expected_tgt_fp}'"
            ),
        ))
        rejection_reasons.append("TARGET_FINGERPRINT_MISMATCH")
    else:
        checks.append(ValidationCheck(
            name="CHECK_TARGET_INTEGRITY",
            status=CHECK_PASS,
            details=f"Target '{manifest.target_name}' verificado com semântica compatível.",
        ))

    # 4. Checagem de Precedência Temporal e Ausência de Overlap
    tr_end = manifest.train_range[1]
    va_start = manifest.val_range[0]
    va_end = manifest.val_range[1]
    te_start = manifest.test_range[0]

    if tr_end >= va_start or va_end >= te_start:
        checks.append(ValidationCheck(
            name="CHECK_TEMPORAL_ORDER",
            status=CHECK_FAIL,
            details=(
                f"Overlap temporal detectado: Train_end ({tr_end}) >= Val_start ({va_start}) "
                f"ou Val_end ({va_end}) >= Test_start ({te_start})"
            ),
        ))
        rejection_reasons.append("TEMPORAL_OVERLAP_DETECTED")
    elif manifest.train_samples <= 0 or manifest.validation_samples <= 0 or manifest.test_samples <= 0:
        checks.append(ValidationCheck(
            name="CHECK_TEMPORAL_ORDER",
            status=CHECK_FAIL,
            details="Partições com contagem de amostras vazias ou inválidas.",
        ))
        rejection_reasons.append("EMPTY_PARTITIONS_DETECTED")
    else:
        checks.append(ValidationCheck(
            name="CHECK_TEMPORAL_ORDER",
            status=CHECK_PASS,
            details=f"Ordenação cronológica estrita: Train ({tr_end}) < Val ({va_start}) < Test ({te_start}).",
        ))

    # 5. Checagem de Anti-Leakage (Shuffle e Preprocessing)
    if manifest.shuffle:
        checks.append(ValidationCheck(
            name="CHECK_LEAKAGE_PREVENTION",
            status=CHECK_FAIL,
            details="Dataset foi embaralhado (shuffle=True), violando a causalidade temporal.",
        ))
        rejection_reasons.append("TEMPORAL_SHUFFLE_DETECTED")
    elif not manifest.preprocessing_fit_train_only:
        checks.append(ValidationCheck(
            name="CHECK_LEAKAGE_PREVENTION",
            status=CHECK_FAIL,
            details="Pré-processamento não foi ajustado exclusivamente no Treino (fit_train_only=False).",
        ))
        rejection_reasons.append("PREPROCESSING_LEAKAGE_DETECTED")
    else:
        checks.append(ValidationCheck(
            name="CHECK_LEAKAGE_PREVENTION",
            status=CHECK_PASS,
            details="Split sem shuffle e pré-processamento ajustado exclusivamente em Treino.",
        ))

    # 6. Checagem de Integridade do Identificador do Modelo
    recomputed_id = compute_model_id(manifest.to_dict())
    if manifest.model_id != recomputed_id:
        checks.append(ValidationCheck(
            name="CHECK_MODEL_ID_INTEGRITY",
            status=CHECK_FAIL,
            details=f"Model ID inconsistente: '{manifest.model_id}' != '{recomputed_id}'",
        ))
        rejection_reasons.append("MODEL_ID_INCONSISTENCY")
    else:
        checks.append(ValidationCheck(
            name="CHECK_MODEL_ID_INTEGRITY",
            status=CHECK_PASS,
            details="Identificador do modelo 100% determinístico e verificado.",
        ))

    # 7. Checagem de Desempenho Out-of-Sample vs Baseline
    # Regra de Generalização: A decisão é estritamente baseada em Validação e Teste (OOS), nunca em Treino.
    # O modelo DEVE demonstrar melhoria clara sobre o baseline no conjunto de validação ou teste.
    mod_val_mae = manifest.metrics_validation.get("mae")
    base_val_mae = manifest.baseline_metrics_validation.get("mae")
    mod_test_mae = manifest.metrics_test.get("mae")
    base_test_mae = manifest.baseline_metrics_test.get("mae")

    if mod_val_mae is None or base_val_mae is None or mod_test_mae is None or base_test_mae is None:
        checks.append(ValidationCheck(
            name="CHECK_BASELINE_SUPERIORITY_OOS",
            status=CHECK_FAIL,
            details="Métricas de MAE ausentes para comparação contra baseline.",
        ))
        rejection_reasons.append("MISSING_OOS_METRICS")
    else:
        val_better = mod_val_mae < base_val_mae
        test_better = mod_test_mae < base_test_mae

        if not val_better and not test_better:
            checks.append(ValidationCheck(
                name="CHECK_BASELINE_SUPERIORITY_OOS",
                status=CHECK_FAIL,
                details=(
                    f"Modelo inferior ao baseline em Validação (MAE: {mod_val_mae:.6f} vs Base: {base_val_mae:.6f}) "
                    f"e em Teste (MAE: {mod_test_mae:.6f} vs Base: {base_test_mae:.6f})."
                ),
            ))
            rejection_reasons.append("MODEL_DOES_NOT_BEAT_BASELINE")
        elif not test_better:
            checks.append(ValidationCheck(
                name="CHECK_BASELINE_SUPERIORITY_OOS",
                status=CHECK_FAIL,
                details=(
                    f"Modelo superou baseline em Validação mas falhou no Teste OOS "
                    f"(MAE: {mod_test_mae:.6f} vs Base: {base_test_mae:.6f})."
                ),
            ))
            rejection_reasons.append("MODEL_DOES_NOT_BEAT_BASELINE_ON_TEST")
        else:
            checks.append(ValidationCheck(
                name="CHECK_BASELINE_SUPERIORITY_OOS",
                status=CHECK_PASS,
                details=(
                    f"Modelo superou o baseline em Validação (MAE: {mod_val_mae:.6f} vs {base_val_mae:.6f}) "
                    f"e em Teste (MAE: {mod_test_mae:.6f} vs {base_test_mae:.6f})."
                ),
            ))

    # Consolidação do Veredito
    has_failures = any(c.status == CHECK_FAIL for c in checks)
    if has_failures:
        verdict = STATUS_REJECTED
        primary_reason = rejection_reasons[0] if rejection_reasons else "VALIDATION_FAILED"
        summary = (
            f"Modelo REJEITADO no Validation Gate: {len(rejection_reasons)} falha(s) detectada(s). "
            f"Motivo principal: {primary_reason}."
        )
    else:
        verdict = STATUS_VALIDATED
        primary_reason = "MODEL_VALIDATED_ALL_CRITERIA"
        summary = "Modelo formalmente VALIDADO pelo Validation Gate com conformidade metodológica e superioridade OOS."

    report = ValidationReport(
        model_id=manifest.model_id,
        verdict=verdict,
        validated_at=now_iso,
        checks=checks,
        reason=primary_reason,
        summary=summary,
    )

    return verdict, report


# =============================================================================
# 5. STORAGE LOCAL E REGISTRY (SQLITE + AUDIT LOG)
# =============================================================================

from contextlib import contextmanager
from typing import Generator


class ModelRegistry:
    """Registry de modelos de pesquisa local, auditável, append-oriented e persistido em SQLite."""

    def __init__(self, db_path: str | Path = "data/lab/results/model_registry/model_registry.sqlite3") -> None:
        self.db_path = Path(db_path)
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Abre conexão SQLite e garante fechamento estrito (evita locks em Windows)."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def close(self) -> None:
        """Operação no-op mantida para compatibilidade de ciclo de vida."""
        pass

    def _init_db(self) -> None:
        """Cria as tabelas de registry e log de auditoria imutável."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS model_registry (
                    model_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    status_reason TEXT NOT NULL,
                    dataset_id TEXT NOT NULL,
                    dataset_fingerprint TEXT NOT NULL,
                    source TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    target_name TEXT NOT NULL,
                    target_fingerprint TEXT NOT NULL,
                    feature_set_version TEXT NOT NULL,
                    feature_fingerprint TEXT NOT NULL,
                    model_type TEXT NOT NULL,
                    train_samples INTEGER NOT NULL,
                    validation_samples INTEGER NOT NULL,
                    test_samples INTEGER NOT NULL,
                    manifest_json TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS model_audit_log (
                    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model_id TEXT NOT NULL,
                    previous_status TEXT,
                    new_status TEXT NOT NULL,
                    transition_reason TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    report_json TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_registry_status ON model_registry(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_model_id ON model_audit_log(model_id)")
            conn.commit()

    def register_candidate(self, manifest: ModelManifest) -> ModelManifest:
        """Registra um novo modelo candidato no registry (idempotente se idêntico)."""
        manifest_dict = manifest.to_dict()
        manifest_json = json.dumps(manifest_dict, sort_keys=True, indent=2)
        now_iso = datetime.now(timezone.utc).isoformat()

        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT manifest_json, status FROM model_registry WHERE model_id = ?",
                (manifest.model_id,),
            ).fetchone()

            if row is not None:
                # Modelo já registrado: verifica se o conteúdo é estritamente idêntico
                existing_dict = json.loads(row["manifest_json"])
                # Compara campos essenciais de identidade
                if (
                    existing_dict.get("dataset_fingerprint") != manifest.dataset_fingerprint
                    or existing_dict.get("feature_fingerprint") != manifest.feature_fingerprint
                    or existing_dict.get("target_fingerprint") != manifest.target_fingerprint
                ):
                    raise ValueError(
                        f"Conflito de integridade: model_id '{manifest.model_id}' já existe "
                        "com conteúdo científico diferente! Não é permitido sobrescrever registros."
                    )
                # Idempotente: retorna o modelo já registrado
                return ModelManifest.from_dict(existing_dict)

            # Inserção de novo candidato
            conn.execute(
                """
                INSERT INTO model_registry (
                    model_id, created_at, updated_at, status, status_reason,
                    dataset_id, dataset_fingerprint, source, symbol, timeframe,
                    target_name, target_fingerprint, feature_set_version, feature_fingerprint,
                    model_type, train_samples, validation_samples, test_samples, manifest_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    manifest.model_id,
                    manifest.created_at,
                    now_iso,
                    STATUS_CANDIDATE,
                    manifest.status_reason,
                    manifest.dataset_id,
                    manifest.dataset_fingerprint,
                    manifest.source,
                    manifest.symbol,
                    manifest.timeframe,
                    manifest.target_name,
                    manifest.target_fingerprint,
                    manifest.feature_set_version,
                    manifest.feature_fingerprint,
                    manifest.model_type,
                    manifest.train_samples,
                    manifest.validation_samples,
                    manifest.test_samples,
                    manifest_json,
                ),
            )
            # Log de auditoria append-only
            conn.execute(
                """
                INSERT INTO model_audit_log (
                    model_id, previous_status, new_status, transition_reason, timestamp, report_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    manifest.model_id,
                    None,
                    STATUS_CANDIDATE,
                    "Initial candidate registration",
                    now_iso,
                    None,
                ),
            )
            conn.commit()

        return manifest

    def get_model(self, model_id: str) -> ModelManifest | None:
        """Recupera um modelo pelo seu ID determinístico."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT manifest_json FROM model_registry WHERE model_id = ?",
                (model_id,),
            ).fetchone()
            if row is None:
                return None
            return ModelManifest.from_dict(json.loads(row["manifest_json"]))

    def list_models(self, status: str | None = None) -> list[ModelManifest]:
        """Lista modelos registrados, com filtro opcional por status."""
        query = "SELECT manifest_json FROM model_registry"
        params: list[Any] = []
        if status is not None:
            if status not in VALID_STATUSES:
                raise ValueError(f"Status inválido para filtro: '{status}'. Opções: {VALID_STATUSES}")
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY created_at ASC"

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [ModelManifest.from_dict(json.loads(r["manifest_json"])) for r in rows]

    def validate_candidate(
        self,
        model_id: str,
        expected_dataset_fingerprint: str | None = None,
    ) -> ModelManifest:
        """Executa o Validation Gate sobre um candidato e registra a transição de estado imutável."""
        model = self.get_model(model_id)
        if model is None:
            raise KeyError(f"Modelo não encontrado para validação: '{model_id}'")

        if model.status not in (STATUS_CANDIDATE, STATUS_REJECTED):
            logger.info("Modelo '%s' já possui status terminal ou validado: '%s'", model_id, model.status)
            return model

        new_status, report = validate_model_candidate(
            model,
            expected_dataset_fingerprint=expected_dataset_fingerprint,
        )
        now_iso = datetime.now(timezone.utc).isoformat()

        # Atualiza o manifesto em memória
        updated_dict = model.to_dict()
        updated_dict["status"] = new_status
        updated_dict["status_reason"] = report.reason
        updated_dict["validation_report"] = report.to_dict()
        new_manifest = ModelManifest.from_dict(updated_dict)
        new_manifest_json = json.dumps(new_manifest.to_dict(), sort_keys=True, indent=2)

        # Transição atômica no banco com log de auditoria append-only
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE model_registry
                SET status = ?, status_reason = ?, updated_at = ?, manifest_json = ?
                WHERE model_id = ?
                """,
                (new_status, report.reason, now_iso, new_manifest_json, model_id),
            )
            conn.execute(
                """
                INSERT INTO model_audit_log (
                    model_id, previous_status, new_status, transition_reason, timestamp, report_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    model_id,
                    model.status,
                    new_status,
                    report.reason,
                    now_iso,
                    json.dumps(report.to_dict()),
                ),
            )
            conn.commit()

        return new_manifest

    def reject_model(self, model_id: str, reason: str = "Manually rejected by researcher") -> ModelManifest:
        """Rejeita explicitamente um modelo registrando o motivo no histórico."""
        model = self.get_model(model_id)
        if model is None:
            raise KeyError(f"Modelo não encontrado para rejeição: '{model_id}'")

        now_iso = datetime.now(timezone.utc).isoformat()
        updated_dict = model.to_dict()
        updated_dict["status"] = STATUS_REJECTED
        updated_dict["status_reason"] = reason
        new_manifest = ModelManifest.from_dict(updated_dict)
        new_manifest_json = json.dumps(new_manifest.to_dict(), sort_keys=True, indent=2)

        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE model_registry
                SET status = ?, status_reason = ?, updated_at = ?, manifest_json = ?
                WHERE model_id = ?
                """,
                (STATUS_REJECTED, reason, now_iso, new_manifest_json, model_id),
            )
            conn.execute(
                """
                INSERT INTO model_audit_log (
                    model_id, previous_status, new_status, transition_reason, timestamp, report_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (model_id, model.status, STATUS_REJECTED, reason, now_iso, None),
            )
            conn.commit()

        return new_manifest

    def revoke_model(self, model_id: str, reason: str = "Revoked due to integrity issue or new evidence") -> ModelManifest:
        """Revoga um modelo anteriormente VALIDATED sem apagar o histórico."""
        model = self.get_model(model_id)
        if model is None:
            raise KeyError(f"Modelo não encontrado para revogação: '{model_id}'")

        now_iso = datetime.now(timezone.utc).isoformat()
        updated_dict = model.to_dict()
        updated_dict["status"] = STATUS_REVOKED
        updated_dict["status_reason"] = reason
        new_manifest = ModelManifest.from_dict(updated_dict)
        new_manifest_json = json.dumps(new_manifest.to_dict(), sort_keys=True, indent=2)

        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE model_registry
                SET status = ?, status_reason = ?, updated_at = ?, manifest_json = ?
                WHERE model_id = ?
                """,
                (STATUS_REVOKED, reason, now_iso, new_manifest_json, model_id),
            )
            conn.execute(
                """
                INSERT INTO model_audit_log (
                    model_id, previous_status, new_status, transition_reason, timestamp, report_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (model_id, model.status, STATUS_REVOKED, reason, now_iso, None),
            )
            conn.commit()

        return new_manifest

    def get_latest_validated(self) -> ModelManifest | None:
        """Consulta o modelo VALIDATED mais recente.

        IMPORTANTE: Função estritamente de consulta para pesquisa/análise.
        NUNCA conectar ao Paper Runner operacional.
        """
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT manifest_json FROM model_registry
                WHERE status = ?
                ORDER BY updated_at DESC, created_at DESC
                LIMIT 1
                """,
                (STATUS_VALIDATED,),
            ).fetchone()
            if row is None:
                return None
            return ModelManifest.from_dict(json.loads(row["manifest_json"]))

    def get_audit_history(self, model_id: str) -> list[dict[str, Any]]:
        """Retorna o histórico completo e cronológico de transições de um modelo."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT log_id, model_id, previous_status, new_status, transition_reason, timestamp, report_json
                FROM model_audit_log
                WHERE model_id = ?
                ORDER BY log_id ASC
                """,
                (model_id,),
            ).fetchall()
            return [dict(r) for r in rows]


# =============================================================================
# 6. EXPORTAÇÃO DE RELATÓRIOS E ARTEFATOS
# =============================================================================

def export_registry_reports(
    registry: ModelRegistry,
    output_dir: str | Path = "data/lab/results/model_registry",
) -> dict[str, Path]:
    """Exporta relatórios consolidados em CSV e JSON para auditoria do Registry."""
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    models = registry.list_models()

    # 1. registry_models.json
    models_json_file = out_path / "registry_models.json"
    with open(models_json_file, "w", encoding="utf-8") as f:
        json.dump([m.to_dict() for m in models], f, indent=2)

    # 2. registry_models.csv
    models_csv_file = out_path / "registry_models.csv"
    csv_rows = []
    for m in models:
        csv_rows.append({
            "model_id": m.model_id,
            "status": m.status,
            "status_reason": m.status_reason,
            "model_type": m.model_type,
            "target": m.target_name,
            "symbol": m.symbol,
            "timeframe": m.timeframe,
            "train_samples": m.train_samples,
            "val_samples": m.validation_samples,
            "test_samples": m.test_samples,
            "val_mae": m.metrics_validation.get("mae"),
            "base_val_mae": m.baseline_metrics_validation.get("mae"),
            "test_mae": m.metrics_test.get("mae"),
            "base_test_mae": m.baseline_metrics_test.get("mae"),
            "test_r2": m.metrics_test.get("r2"),
            "created_at": m.created_at,
        })

    with open(models_csv_file, "w", newline="", encoding="utf-8") as f:
        if csv_rows:
            writer = csv.DictWriter(f, fieldnames=list(csv_rows[0].keys()))
            writer.writeheader()
            writer.writerows(csv_rows)
        else:
            writer = csv.writer(f)
            writer.writerow(["model_id", "status", "status_reason"])

    # 3. validation_report.json (consolidação dos relatórios de validação)
    validation_reports_file = out_path / "validation_report.json"
    reports = {m.model_id: m.validation_report.to_dict() for m in models if m.validation_report}
    with open(validation_reports_file, "w", encoding="utf-8") as f:
        json.dump(reports, f, indent=2)

    return {
        "models_json": models_json_file,
        "models_csv": models_csv_file,
        "validation_report_json": validation_reports_file,
    }


# =============================================================================
# 7. CLI DE PESQUISA LOCAL
# =============================================================================

def build_cli_parser() -> argparse.ArgumentParser:
    """Constrói o parser para a CLI do Model Registry."""
    parser = argparse.ArgumentParser(
        prog="python -m finbot.lab.model_registry",
        description="CLI do FinBot Model Validation / Registry (FASE 7.9H).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcomando: list
    list_p = subparsers.add_parser("list", help="Lista modelos registrados no registry.")
    list_p.add_argument("--status", choices=[STATUS_CANDIDATE, STATUS_VALIDATED, STATUS_REJECTED, STATUS_REVOKED], help="Filtrar por status.")
    list_p.add_argument("--db", default="data/lab/results/model_registry/model_registry.sqlite3", help="Caminho do banco SQLite do registry.")

    # Subcomando: show
    show_p = subparsers.add_parser("show", help="Exibe detalhes completos de um modelo.")
    show_p.add_argument("model_id", help="Identificador do modelo.")
    show_p.add_argument("--db", default="data/lab/results/model_registry/model_registry.sqlite3", help="Caminho do banco SQLite do registry.")

    # Subcomando: validate
    val_p = subparsers.add_parser("validate", help="Executa o Validation Gate sobre um candidato.")
    val_p.add_argument("model_id", help="Identificador do modelo a ser validado.")
    val_p.add_argument("--dataset", help="Caminho opcional do dataset para verificação de integridade.")
    val_p.add_argument("--db", default="data/lab/results/model_registry/model_registry.sqlite3", help="Caminho do banco SQLite do registry.")

    return parser


def main(argv: list[str] | None = None) -> int:
    """Ponto de entrada da CLI."""
    parser = build_cli_parser()
    args = parser.parse_args(argv)

    registry = ModelRegistry(db_path=args.db)

    if args.command == "list":
        models = registry.list_models(status=args.status)
        print(f"Total de modelos registrados ({args.status or 'ALL'}): {len(models)}")
        for m in models:
            val_mae = m.metrics_validation.get("mae", "N/A")
            base_mae = m.baseline_metrics_validation.get("mae", "N/A")
            print(f"  [{m.status:9s}] {m.model_id} | {m.model_type} | Val MAE: {val_mae} vs Base: {base_mae} | {m.status_reason}")
        return 0

    if args.command == "show":
        m = registry.get_model(args.model_id)
        if m is None:
            print(f"Erro: Modelo '{args.model_id}' não encontrado.", file=sys.stderr)
            return 1
        print(json.dumps(m.to_dict(), indent=2))
        return 0

    if args.command == "validate":
        ds_fp = compute_dataset_fingerprint(args.dataset) if args.dataset else None
        try:
            updated = registry.validate_candidate(args.model_id, expected_dataset_fingerprint=ds_fp)
            print(f"Validação concluída para '{updated.model_id}': Status = {updated.status}")
            print(f"Motivo: {updated.status_reason}")
            return 0 if updated.status == STATUS_VALIDATED else 1
        except Exception as e:
            print(f"Erro ao validar modelo: {e}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
