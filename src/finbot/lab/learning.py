"""Módulo de Aprendizado Adaptativo (Adaptive Learning) do FinBot (FASE 7.9G).

Implementa o pipeline determinístico, temporalmente estrito e livre de leakage para:
1. Auditoria e verificação de suficiência do Experience Dataset.
2. Extração de matrizes de features (FEATURE-SAFE) e target (OUTCOME-ONLY).
3. Split estritamente temporal (Train 60% / Validation 20% / Test 20%) sem shuffle.
4. Pré-processamento com scaler ajustado exclusivamente na partição de Treino.
5. Baseline determinístico (DummyRegressor / média histórica de Treino).
6. Primeiro modelo regularizado (Ridge Regression).
7. Avaliação estatística e econômica em Validation e Test isolado.
8. Geração de relatórios e artefatos de reprodutibilidade em data/lab/results/adaptive_learning/.

REGRAS ARQUITETURAIS:
- 100% offline, reproduzível e isolado do bot operacional (Paper Runner / Risk Engine).
- O modelo gerado NÃO toma decisões financeiras e NÃO emite ordens.
- Zero dependências obrigatórias adicionadas ao ambiente de produção (.venv).
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import time
from typing import Any, Sequence

import numpy as np
import pandas as pd

# Suporte dual a scikit-learn (ambiente de pesquisa) com fallback exato em numpy
try:
    from sklearn.dummy import DummyRegressor
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False

from finbot.backtest import FinBotSMAStrategy, FractionalBacktest, candles_to_dataframe
from finbot.experience import (
    ExperienceRecord,
    create_experience_from_backtest_trade,
)
from finbot.features import (
    FeatureSet,
    LabelSet,
    build_labels,
    extract_features,
)

logger = logging.getLogger(__name__)


# =============================================================================
# 1. ESTRUTURAS DE AUDITORIA E SUFICIÊNCIA
# =============================================================================

@dataclass(frozen=True)
class DatasetAuditResult:
    """Resultado da auditoria exploratória do Experience Dataset."""

    total_experiences: int
    experiences_by_source: dict[str, int]
    experiences_by_symbol: dict[str, int]
    experiences_by_timeframe: dict[str, int]
    first_decision_at: str | None
    last_decision_at: str | None
    with_complete_features: int
    with_future_return_5: int
    with_future_return_20: int
    with_future_return_50: int
    with_future_return_100: int
    with_outcome: int
    missing_values_count: int
    duplicate_experiences_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def audit_experience_dataset(
    experiences: Sequence[ExperienceRecord],
    candles: Sequence[Any] | None = None,
) -> DatasetAuditResult:
    """Audita rigorosamente uma coleção de experiências antes de qualquer modelagem."""
    total = len(experiences)
    if total == 0:
        return DatasetAuditResult(
            total_experiences=0,
            experiences_by_source={},
            experiences_by_symbol={},
            experiences_by_timeframe={},
            first_decision_at=None,
            last_decision_at=None,
            with_complete_features=0,
            with_future_return_5=0,
            with_future_return_20=0,
            with_future_return_50=0,
            with_future_return_100=0,
            with_outcome=0,
            missing_values_count=0,
            duplicate_experiences_count=0,
        )

    by_source: dict[str, int] = {}
    by_symbol: dict[str, int] = {}
    by_tf: dict[str, int] = {}
    timestamps: list[str] = []
    seen_keys: set[tuple[str, str]] = set()
    duplicates = 0

    complete_features = 0
    with_ret_5 = 0
    with_ret_20 = 0
    with_ret_50 = 0
    with_ret_100 = 0
    with_outcome = 0
    missing_count = 0

    for exp in experiences:
        # Contagem por proveniência
        by_source[exp.source] = by_source.get(exp.source, 0) + 1
        by_symbol[exp.decision.symbol] = by_symbol.get(exp.decision.symbol, 0) + 1
        by_tf[exp.decision.timeframe] = by_tf.get(exp.decision.timeframe, 0) + 1
        timestamps.append(exp.decision.decision_at)

        key = (exp.source, exp.source_id)
        if key in seen_keys:
            duplicates += 1
        seen_keys.add(key)

        # Checagem de features
        f_dict = extract_features(exp, historical_candles=candles).to_dict()
        if None not in [f_dict["price"], f_dict["open"], f_dict["close"], f_dict["sma_short"], f_dict["sma_long"]]:
            complete_features += 1
        else:
            missing_count += 1

        # Checagem de labels
        if candles:
            try:
                labs = build_labels(exp, candles=candles, horizons=(5, 20, 50, 100))
                if labs.future_return_5 is not None:
                    with_ret_5 += 1
                if labs.future_return_20 is not None:
                    with_ret_20 += 1
                if labs.future_return_50 is not None:
                    with_ret_50 += 1
                if labs.future_return_100 is not None:
                    with_ret_100 += 1
            except Exception:
                pass
        elif exp.outcome:
            if exp.outcome.future_return_5 is not None:
                with_ret_5 += 1
            if exp.outcome.future_return_20 is not None:
                with_ret_20 += 1
            if exp.outcome.future_return_50 is not None:
                with_ret_50 += 1
            if exp.outcome.future_return_100 is not None:
                with_ret_100 += 1

        if exp.outcome and exp.outcome.outcome is not None:
            with_outcome += 1

    sorted_ts = sorted(timestamps)
    return DatasetAuditResult(
        total_experiences=total,
        experiences_by_source=by_source,
        experiences_by_symbol=by_symbol,
        experiences_by_timeframe=by_tf,
        first_decision_at=sorted_ts[0] if sorted_ts else None,
        last_decision_at=sorted_ts[-1] if sorted_ts else None,
        with_complete_features=complete_features,
        with_future_return_5=with_ret_5,
        with_future_return_20=with_ret_20,
        with_future_return_50=with_ret_50,
        with_future_return_100=with_ret_100,
        with_outcome=with_outcome,
        missing_values_count=missing_count,
        duplicate_experiences_count=duplicates,
    )


def check_sample_sufficiency(n_usable: int, min_samples: int = 50) -> tuple[bool, str]:
    """Verifica se a quantidade de amostras utilizáveis permite modelagem estatística válida."""
    if n_usable < min_samples:
        return False, "INSUFFICIENT_SAMPLE"
    return True, "SUFFICIENT"


# =============================================================================
# 2. CONSTRUÇÃO DE DATASET DE APRENDIZADO
# =============================================================================

FEATURE_NAMES = [
    "price",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "short_window",
    "long_window",
    "sma_short",
    "sma_long",
    "sma_distance",
    "sma_ratio",
    "hour",
    "day_of_week",
]

FORBIDDEN_OUTCOME_FIELDS = {
    "outcome_at",
    "exit_price",
    "realized_pnl",
    "realized_return",
    "fees",
    "mfe",
    "mae",
    "trade_duration",
    "future_return_5",
    "future_return_20",
    "future_return_50",
    "future_return_100",
    "outcome",
}


@dataclass(frozen=True)
class LearningDataset:
    """Dataset estruturado de aprendizado pronto para particionamento temporal."""

    X: np.ndarray  # Matriz 2D de features (N, D)
    y: np.ndarray  # Vetor 1D do target (N,)
    feature_names: list[str]
    target_name: str
    timestamps: list[str]
    experience_ids: list[str]
    total_samples: int

    def __post_init__(self) -> None:
        if len(self.X) != len(self.y):
            raise ValueError(f"Dimensões incompatíveis: X tem {len(self.X)} linhas e y tem {len(self.y)}.")


def build_learning_dataset(
    experiences: Sequence[ExperienceRecord],
    candles: Sequence[Any],
    target_name: str = "future_return_20",
    feature_names: Sequence[str] = FEATURE_NAMES,
) -> LearningDataset:
    """Extrai matrizes (X, y) estritamente ordenadas cronologicamente a partir de experiências."""
    # Ordena experiências por decision_at para garantir temporalidade irrestrita
    sorted_exps = sorted(experiences, key=lambda e: e.decision.decision_at)

    rows_X: list[list[float]] = []
    rows_y: list[float] = []
    ts_list: list[str] = []
    id_list: list[str] = []

    horizon_map = {"future_return_5": 5, "future_return_20": 20, "future_return_50": 50, "future_return_100": 100}
    target_horizon = horizon_map.get(target_name, 20)

    for exp in sorted_exps:
        feats = extract_features(exp, historical_candles=candles)
        labs = build_labels(exp, candles=candles, horizons=[target_horizon])

        target_val = getattr(labs, target_name, None)
        if target_val is None:
            # Pula registros cujo target futuro é desconhecido (NULL-safe)
            continue

        f_dict = feats.to_dict()

        # Auditoria formal anti-leakage: garante que nenhuma feature é campo proibido
        for fname in feature_names:
            if fname in FORBIDDEN_OUTCOME_FIELDS:
                raise ValueError(f"Violação grave de leakage: campo de outcome '{fname}' solicitado como feature!")

        # Monta vetor de features
        row: list[float] = []
        skip_record = False
        for fname in feature_names:
            val = f_dict.get(fname)
            if val is None or np.isnan(val):
                skip_record = True
                break
            row.append(float(val))

        if not skip_record:
            rows_X.append(row)
            rows_y.append(float(target_val))
            ts_list.append(exp.decision.decision_at)
            id_list.append(exp.experience_id)

    X_arr = np.array(rows_X, dtype=np.float64) if rows_X else np.empty((0, len(feature_names)), dtype=np.float64)
    y_arr = np.array(rows_y, dtype=np.float64) if rows_y else np.empty((0,), dtype=np.float64)

    return LearningDataset(
        X=X_arr,
        y=y_arr,
        feature_names=list(feature_names),
        target_name=target_name,
        timestamps=ts_list,
        experience_ids=id_list,
        total_samples=len(y_arr),
    )


# =============================================================================
# 3. SPLIT TEMPORAL SEM SHUFFLE
# =============================================================================

@dataclass(frozen=True)
class TemporalSplitResult:
    """Partições resultantes de divisão cronológica estrita (Train / Validation / Test)."""

    X_train: np.ndarray
    y_train: np.ndarray
    ts_train: list[str]
    ids_train: list[str]

    X_val: np.ndarray
    y_val: np.ndarray
    ts_val: list[str]
    ids_val: list[str]

    X_test: np.ndarray
    y_test: np.ndarray
    ts_test: list[str]
    ids_test: list[str]

    n_train: int
    n_val: int
    n_test: int
    train_range: tuple[str, str]
    val_range: tuple[str, str]
    test_range: tuple[str, str]


def temporal_train_val_test_split(
    dataset: LearningDataset,
    train_ratio: float = 0.60,
    val_ratio: float = 0.20,
    test_ratio: float = 0.20,
) -> TemporalSplitResult:
    """Divide o dataset cronologicamente sem embaralhamento (NO SHUFFLE).

    Garantia de Precedência Temporal:
    max(Train_ts) < min(Val_ts) e max(Val_ts) < min(Test_ts).
    """
    total = dataset.total_samples
    if total < 3:
        raise ValueError(f"Dataset com amostras insuficientes para divisão 3-way: {total} amostras.")

    ratio_sum = round(train_ratio + val_ratio + test_ratio, 6)
    if ratio_sum != 1.0:
        raise ValueError(f"Proporções de split devem somar 1.0 (recebido: {ratio_sum}).")

    n_train = int(total * train_ratio)
    n_val = int(total * val_ratio)
    n_test = total - n_train - n_val

    if n_train == 0 or n_val == 0 or n_test == 0:
        raise ValueError(
            f"Divisão gerou partições vazias (Train={n_train}, Val={n_val}, Test={n_test}). "
            "Aumente o tamanho da amostra."
        )

    val_start = n_train
    val_end = n_train + n_val

    X_tr = dataset.X[:n_train]
    y_tr = dataset.y[:n_train]
    ts_tr = dataset.timestamps[:n_train]
    ids_tr = dataset.experience_ids[:n_train]

    X_va = dataset.X[val_start:val_end]
    y_va = dataset.y[val_start:val_end]
    ts_va = dataset.timestamps[val_start:val_end]
    ids_va = dataset.experience_ids[val_start:val_end]

    X_te = dataset.X[val_end:]
    y_te = dataset.y[val_end:]
    ts_te = dataset.timestamps[val_end:]
    ids_te = dataset.experience_ids[val_end:]

    # Validação matemática estrita de ausência de overlap e ordenação temporal
    if any(dataset.timestamps[i] > dataset.timestamps[i + 1] for i in range(len(dataset.timestamps) - 1)):
        raise ValueError("Data leakage temporal detectado: dataset não está estritamente ordenado cronologicamente.")

    if max(ts_tr) >= min(ts_va):
        raise ValueError(f"Data leakage temporal detectado: Train max ({max(ts_tr)}) >= Val min ({min(ts_va)}).")
    if max(ts_va) >= min(ts_te):
        raise ValueError(f"Data leakage temporal detectado: Val max ({max(ts_va)}) >= Test min ({min(ts_te)}).")

    return TemporalSplitResult(
        X_train=X_tr,
        y_train=y_tr,
        ts_train=ts_tr,
        ids_train=ids_tr,
        X_val=X_va,
        y_val=y_va,
        ts_val=ts_va,
        ids_val=ids_va,
        X_test=X_te,
        y_test=y_te,
        ts_test=ts_te,
        ids_test=ids_te,
        n_train=len(y_tr),
        n_val=len(y_va),
        n_test=len(y_te),
        train_range=(ts_tr[0], ts_tr[-1]),
        val_range=(ts_va[0], ts_va[-1]),
        test_range=(ts_te[0], ts_te[-1]),
    )


# =============================================================================
# 4. PRÉ-PROCESSAMENTO SEGURO (SCALER FIT SOMENTE NO TRAIN)
# =============================================================================

class PureNumpyScaler:
    """Scaler padrão puramente implementado em NumPy sem scikit-learn."""

    def __init__(self) -> None:
        self.mean_: np.ndarray | None = None
        self.scale_: np.ndarray | None = None

    def fit(self, X: np.ndarray) -> PureNumpyScaler:
        self.mean_ = np.mean(X, axis=0)
        scale = np.std(X, axis=0)
        # Proteção contra desvio padrão nulo
        scale[scale == 0.0] = 1.0
        self.scale_ = scale
        return self

    def transform(self, X: np.ndarray) -> np.ndarray:
        if self.mean_ is None or self.scale_ is None:
            raise RuntimeError("Scaler não ajustado (fit) previamente.")
        return (X - self.mean_) / self.scale_

    def fit_transform(self, X: np.ndarray) -> np.ndarray:
        return self.fit(X).transform(X)


def fit_and_scale_features(
    X_train: np.ndarray,
    X_val: np.ndarray,
    X_test: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, Any]:
    """Ajusta o scaler EXCLUSIVAMENTE em X_train e projeta sobre Val e Test sem vazamento."""
    if HAS_SKLEARN:
        scaler = StandardScaler()
    else:
        scaler = PureNumpyScaler()

    # FIT somente no Train
    scaler.fit(X_train)

    X_train_scaled = scaler.transform(X_train)
    X_val_scaled = scaler.transform(X_val)
    X_test_scaled = scaler.transform(X_test)

    return X_train_scaled, X_val_scaled, X_test_scaled, scaler


# =============================================================================
# 5. MODELOS (BASELINE & RIDGE)
# =============================================================================

class PureNumpyBaseline:
    """Baseline determinístico constante baseado na média do Treino."""

    def __init__(self) -> None:
        self.mean_value_: float = 0.0

    def fit(self, y: np.ndarray) -> PureNumpyBaseline:
        self.mean_value_ = float(np.mean(y)) if len(y) > 0 else 0.0
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        return np.full(len(X), self.mean_value_, dtype=np.float64)


class PureNumpyRidge:
    """Implementação exata da Regressão Ridge via equações normais em NumPy."""

    def __init__(self, alpha: float = 1.0) -> None:
        self.alpha = alpha
        self.coef_: np.ndarray | None = None
        self.intercept_: float = 0.0

    def fit(self, X: np.ndarray, y: np.ndarray) -> PureNumpyRidge:
        # Centra y e X para resolver intercept analiticamente
        y_mean = float(np.mean(y))
        X_mean = np.mean(X, axis=0)
        X_c = X - X_mean
        y_c = y - y_mean

        n_features = X.shape[1]
        A = X_c.T @ X_c + self.alpha * np.eye(n_features)
        b = X_c.T @ y_c

        self.coef_ = np.linalg.solve(A, b)
        self.intercept_ = y_mean - float(X_mean @ self.coef_)
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        if self.coef_ is None:
            raise RuntimeError("Modelo Ridge não ajustado.")
        return X @ self.coef_ + self.intercept_


def fit_baseline_model(y_train: np.ndarray) -> Any:
    """Ajusta o modelo baseline determinístico sobre y_train."""
    if HAS_SKLEARN:
        model = DummyRegressor(strategy="mean")
        model.fit(np.zeros((len(y_train), 1)), y_train)
        return model
    model = PureNumpyBaseline()
    model.fit(y_train)
    return model


def fit_ridge_model(X_train: np.ndarray, y_train: np.ndarray, alpha: float = 1.0) -> Any:
    """Ajusta o modelo Ridge regularizado sobre dados escalados de Treino."""
    if HAS_SKLEARN:
        model = Ridge(alpha=alpha, random_state=42)
        model.fit(X_train, y_train)
        return model
    model = PureNumpyRidge(alpha=alpha)
    model.fit(X_train, y_train)
    return model


def predict_model(model: Any, X: np.ndarray) -> np.ndarray:
    """Emite predições compatível com scikit-learn e fallback pure numpy."""
    if HAS_SKLEARN and isinstance(model, DummyRegressor):
        return model.predict(np.zeros((len(X), 1)))
    return model.predict(X)


# =============================================================================
# 6. MÉTRICAS ESTATÍSTICAS E ECONÔMICAS
# =============================================================================

@dataclass(frozen=True)
class LearningMetrics:
    """Métricas multidimensionais de avaliação de modelos."""

    mae: float
    rmse: float
    r2: float
    directional_accuracy: float
    correlation: float | None
    mean_actual: float
    mean_predicted: float
    median_actual: float
    median_predicted: float
    economic_positive_pred_return: float | None  # Retorno real médio quando predição > 0
    economic_negative_pred_return: float | None  # Retorno real médio quando predição <= 0
    economic_positive_count: int
    economic_negative_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def calculate_learning_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> LearningMetrics:
    """Calcula estatísticas de erro, correlação e diagnóstico econômico."""
    n = len(y_true)
    if n == 0:
        return LearningMetrics(
            mae=0.0, rmse=0.0, r2=0.0, directional_accuracy=0.0, correlation=None,
            mean_actual=0.0, mean_predicted=0.0, median_actual=0.0, median_predicted=0.0,
            economic_positive_pred_return=None, economic_negative_pred_return=None,
            economic_positive_count=0, economic_negative_count=0,
        )

    mae = float(np.mean(np.abs(y_true - y_pred)))
    rmse = float(np.sqrt(np.mean((y_true - y_pred) ** 2)))

    # R²
    ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2))
    ss_res = float(np.sum((y_true - y_pred) ** 2))
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 0.0 else 0.0

    # Acurácia direcional (concordância de sinal)
    sign_true = np.sign(y_true)
    sign_pred = np.sign(y_pred)
    directional_acc = float(np.mean(sign_true == sign_pred))

    # Correlação de Pearson
    corr: float | None = None
    if np.std(y_true) > 1e-12 and np.std(y_pred) > 1e-12:
        c_matrix = np.corrcoef(y_true, y_pred)
        if not np.isnan(c_matrix[0, 1]):
            corr = float(c_matrix[0, 1])

    # Diagnóstico Econômico (retorno médio condicionado ao sinal da predição)
    pos_mask = y_pred > 0.0
    neg_mask = y_pred <= 0.0

    pos_ret: float | None = float(np.mean(y_true[pos_mask])) if np.any(pos_mask) else None
    neg_ret: float | None = float(np.mean(y_true[neg_mask])) if np.any(neg_mask) else None

    return LearningMetrics(
        mae=round(mae, 8),
        rmse=round(rmse, 8),
        r2=round(r2, 6),
        directional_accuracy=round(directional_acc, 4),
        correlation=round(corr, 6) if corr is not None else None,
        mean_actual=round(float(np.mean(y_true)), 8),
        mean_predicted=round(float(np.mean(y_pred)), 8),
        median_actual=round(float(np.median(y_true)), 8),
        median_predicted=round(float(np.median(y_pred)), 8),
        economic_positive_pred_return=round(pos_ret, 8) if pos_ret is not None else None,
        economic_negative_pred_return=round(neg_ret, 8) if neg_ret is not None else None,
        economic_positive_count=int(np.sum(pos_mask)),
        economic_negative_count=int(np.sum(neg_mask)),
    )


# =============================================================================
# 7. EXPERIMENTO COMPLETO E EXPORTAÇÃO
# =============================================================================

@dataclass(frozen=True)
class LearningExperimentResult:
    """Resultado consolidado do experimento de aprendizado adaptativo."""

    status: str  # "COMPLETE" ou "INSUFFICIENT_SAMPLE"
    audit: DatasetAuditResult
    target_name: str
    feature_names: list[str]
    n_train: int
    n_val: int
    n_test: int
    train_range: tuple[str, str]
    val_range: tuple[str, str]
    test_range: tuple[str, str]
    baseline_train_metrics: LearningMetrics
    baseline_val_metrics: LearningMetrics
    baseline_test_metrics: LearningMetrics
    model_train_metrics: LearningMetrics
    model_val_metrics: LearningMetrics
    model_test_metrics: LearningMetrics
    coefficients: dict[str, float]
    intercept: float
    conclusion: str
    execution_time_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "audit": self.audit.to_dict(),
            "target_name": self.target_name,
            "feature_names": self.feature_names,
            "n_train": self.n_train,
            "n_val": self.n_val,
            "n_test": self.n_test,
            "train_range": list(self.train_range),
            "val_range": list(self.val_range),
            "test_range": list(self.test_range),
            "baseline_train": self.baseline_train_metrics.to_dict(),
            "baseline_val": self.baseline_val_metrics.to_dict(),
            "baseline_test": self.baseline_test_metrics.to_dict(),
            "model_train": self.model_train_metrics.to_dict(),
            "model_val": self.model_val_metrics.to_dict(),
            "model_test": self.model_test_metrics.to_dict(),
            "coefficients": self.coefficients,
            "intercept": self.intercept,
            "conclusion": self.conclusion,
            "execution_time_seconds": self.execution_time_seconds,
        }


def run_learning_experiment(
    experiences: Sequence[ExperienceRecord],
    candles: Sequence[Any],
    target_name: str = "future_return_20",
    feature_names: Sequence[str] = FEATURE_NAMES,
    alpha: float = 1.0,
    min_samples: int = 50,
) -> LearningExperimentResult:
    """Executa o pipeline completo da Fase 7.9G de ponta a ponta."""
    start_time = time.perf_counter()

    # 1. Auditoria
    audit_res = audit_experience_dataset(experiences, candles=candles)

    # 2. Construção do Learning Dataset
    dataset = build_learning_dataset(
        experiences=experiences,
        candles=candles,
        target_name=target_name,
        feature_names=feature_names,
    )

    # 3. Suficiência da amostra
    is_sufficient, suff_status = check_sample_sufficiency(dataset.total_samples, min_samples=min_samples)
    if not is_sufficient:
        empty_metrics = calculate_learning_metrics(np.array([]), np.array([]))
        return LearningExperimentResult(
            status=suff_status,
            audit=audit_res,
            target_name=target_name,
            feature_names=list(feature_names),
            n_train=0,
            n_val=0,
            n_test=0,
            train_range=("", ""),
            val_range=("", ""),
            test_range=("", ""),
            baseline_train_metrics=empty_metrics,
            baseline_val_metrics=empty_metrics,
            baseline_test_metrics=empty_metrics,
            model_train_metrics=empty_metrics,
            model_val_metrics=empty_metrics,
            model_test_metrics=empty_metrics,
            coefficients={},
            intercept=0.0,
            conclusion="INSUFFICIENT_SAMPLE: Amostra utilizável insuficiente para treinamento.",
            execution_time_seconds=time.perf_counter() - start_time,
        )

    # 4. Split Temporal
    split = temporal_train_val_test_split(dataset, train_ratio=0.60, val_ratio=0.20, test_ratio=0.20)

    # 5. Pré-processamento sem leakage (FIT exclusivamente no Train)
    X_tr_s, X_va_s, X_te_s, _ = fit_and_scale_features(split.X_train, split.X_val, split.X_test)

    # 6. Baseline
    base_model = fit_baseline_model(split.y_train)
    y_pred_base_tr = predict_model(base_model, split.X_train)
    y_pred_base_va = predict_model(base_model, split.X_val)
    y_pred_base_te = predict_model(base_model, split.X_test)

    base_m_tr = calculate_learning_metrics(split.y_train, y_pred_base_tr)
    base_m_va = calculate_learning_metrics(split.y_val, y_pred_base_va)
    base_m_te = calculate_learning_metrics(split.y_test, y_pred_base_te)

    # 7. Modelo Ridge
    ridge = fit_ridge_model(X_tr_s, split.y_train, alpha=alpha)
    y_pred_model_tr = predict_model(ridge, X_tr_s)
    y_pred_model_va = predict_model(ridge, X_va_s)
    y_pred_model_te = predict_model(ridge, X_te_s)

    mod_m_tr = calculate_learning_metrics(split.y_train, y_pred_model_tr)
    mod_m_va = calculate_learning_metrics(split.y_val, y_pred_model_va)
    mod_m_te = calculate_learning_metrics(split.y_test, y_pred_model_te)

    # Coeficientes
    coefs = ridge.coef_.flatten() if hasattr(ridge, "coef_") else np.zeros(len(feature_names))
    intercept = float(ridge.intercept_) if hasattr(ridge, "intercept_") else 0.0
    coef_dict = {name: round(float(coefs[i]), 8) for i, name in enumerate(feature_names)}

    # Conclusão objetiva e descritiva
    # Critério: modelo reduz MAE/RMSE ou acrescenta acurácia direcional sobre o baseline em Val e Test
    val_improved = mod_m_va.mae < base_m_va.mae or mod_m_va.directional_accuracy > base_m_va.directional_accuracy
    test_improved = mod_m_te.mae < base_m_te.mae or mod_m_te.directional_accuracy > base_m_te.directional_accuracy

    if val_improved and test_improved:
        conclusion = (
            "MODEL_ADDS_INFORMATION: O modelo Ridge regularizado superou o baseline na partição de validação e teste, "
            f"apresentando acurácia direcional de {mod_m_te.directional_accuracy * 100:.1f}% vs "
            f"{base_m_te.directional_accuracy * 100:.1f}% do baseline no Teste."
        )
    elif val_improved and not test_improved:
        conclusion = (
            "INCONCLUSIVE: O modelo superou o baseline em validação, mas não manteve superioridade no teste out-of-sample "
            f"(MAE Test: {mod_m_te.mae:.6f} vs Baseline: {base_m_te.mae:.6f})."
        )
    else:
        conclusion = (
            "MODEL_DOES_NOT_BEAT_BASELINE: O modelo Ridge não conseguiu superar a estimativa estática do baseline "
            f"(MAE Val: {mod_m_va.mae:.6f} vs Baseline: {base_m_va.mae:.6f})."
        )

    elapsed = time.perf_counter() - start_time

    return LearningExperimentResult(
        status="COMPLETE",
        audit=audit_res,
        target_name=target_name,
        feature_names=list(feature_names),
        n_train=split.n_train,
        n_val=split.n_val,
        n_test=split.n_test,
        train_range=split.train_range,
        val_range=split.val_range,
        test_range=split.test_range,
        baseline_train_metrics=base_m_tr,
        baseline_val_metrics=base_m_va,
        baseline_test_metrics=base_m_te,
        model_train_metrics=mod_m_tr,
        model_val_metrics=mod_m_va,
        model_test_metrics=mod_m_te,
        coefficients=coef_dict,
        intercept=intercept,
        conclusion=conclusion,
        execution_time_seconds=round(elapsed, 4),
    )


def extract_canonical_backtest_experiences(
    candles: Sequence[Any],
    symbol: str = "BTC/USDT",
    timeframe: str = "5m",
    short_window: int = 5,
    long_window: int = 10,
    initial_cash: float = 10000.0,
    commission: float = 0.001,
    run_id: str = "canonical_backtest_10k",
) -> list[ExperienceRecord]:
    """Gera experiências canônicas a partir dos trades reais executados pela estratégia SMA 5/10."""
    df = candles_to_dataframe(candles)

    class ConfiguredStrategy(FinBotSMAStrategy):
        pass

    ConfiguredStrategy.short_window = short_window
    ConfiguredStrategy.long_window = long_window

    bt = FractionalBacktest(df, ConfiguredStrategy, cash=initial_cash, commission=commission, finalize_trades=True)
    stats = bt.run()
    trades_df = stats.get("_trades")

    experiences: list[ExperienceRecord] = []
    if trades_df is None or len(trades_df) == 0:
        return experiences

    for idx, row in trades_df.iterrows():
        entry_bar = int(row["EntryBar"])
        dec_candle_idx = entry_bar - 1
        if dec_candle_idx < 0:
            continue

        c = candles[dec_candle_idx]
        candle_ts = c.timestamp if hasattr(c, "timestamp") else c["timestamp"]

        exp = create_experience_from_backtest_trade(
            trade=row,
            symbol=symbol,
            timeframe=timeframe,
            short_window=short_window,
            long_window=long_window,
            run_id=run_id,
            source_id=f"trade_{idx}",
            candle_timestamp=candle_ts,
        )
        experiences.append(exp)

    return experiences


def export_learning_artifacts(
    result: LearningExperimentResult,
    output_dir: str | Path = "data/lab/results/adaptive_learning",
) -> dict[str, Path]:
    """Exporta os artefatos estruturados do experimento para pesquisa reprodutível."""
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # 1. learning_results.json
    results_file = out_path / "learning_results.json"
    with open(results_file, "w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, indent=2)

    # 2. learning_summary.csv
    summary_file = out_path / "learning_summary.csv"
    summary_rows = [
        {"partition": "Train", "model": "Baseline", **result.baseline_train_metrics.to_dict()},
        {"partition": "Train", "model": "Ridge", **result.model_train_metrics.to_dict()},
        {"partition": "Validation", "model": "Baseline", **result.baseline_val_metrics.to_dict()},
        {"partition": "Validation", "model": "Ridge", **result.model_val_metrics.to_dict()},
        {"partition": "Test", "model": "Baseline", **result.baseline_test_metrics.to_dict()},
        {"partition": "Test", "model": "Ridge", **result.model_test_metrics.to_dict()},
    ]
    with open(summary_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
        writer.writeheader()
        writer.writerows(summary_rows)

    # 3. learning_coefficients.csv
    coef_file = out_path / "learning_coefficients.csv"
    with open(coef_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["feature", "coefficient"])
        writer.writeheader()
        for fname, val in result.coefficients.items():
            writer.writerow({"feature": fname, "coefficient": val})
        writer.writerow({"feature": "intercept", "coefficient": result.intercept})

    # 4. learning_manifest.json
    manifest_file = out_path / "learning_manifest.json"
    manifest = {
        "status": result.status,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "target": result.target_name,
        "n_train": result.n_train,
        "n_val": result.n_val,
        "n_test": result.n_test,
        "train_range": result.train_range,
        "val_range": result.val_range,
        "test_range": result.test_range,
        "conclusion": result.conclusion,
        "elapsed_seconds": result.execution_time_seconds,
    }
    with open(manifest_file, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return {
        "results_json": results_file,
        "summary_csv": summary_file,
        "coefficients_csv": coef_file,
        "manifest_json": manifest_file,
    }
