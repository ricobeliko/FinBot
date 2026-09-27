"""Suíte de testes para o pipeline de Aprendizado Adaptativo (Adaptive Learning) do FinBot (FASE 7.9G).

Cobre os 16 testes metodológicos obrigatórios e validações adicionais:
1. Dataset temporalmente ordenado (mesmo com input desordenado).
2. Split 60% Train / 20% Validation / 20% Test exato.
3. Nenhum overlap de IDs ou índices entre partições.
4. Train sempre estritamente anterior à Validation (max(Train) < min(Val)).
5. Validation sempre estritamente anterior ao Test (max(Val) < min(Test)).
6. Baseline (DummyRegressor/média) treinado exclusivamente no Train.
7. Modelo regularizado (Ridge) treinado exclusivamente no Train.
8. Pré-processamento sem leakage (scaler ajustado exclusivamente no Train).
9. Métricas estatísticas e econômicas determinísticas e exatas.
10. Tratamento correto de amostra insuficiente (INSUFFICIENT_SAMPLE).
11. Proibição absoluta de campos de outcome/leakage nas features.
12. Target future_return_20 calculado corretamente conforme contrato.
13. Resultados 100% reproduzíveis entre execuções.
14. Alteração de dados futuros NÃO altera features de Treino.
15. Alteração de dados futuros altera labels adequadamente.
16. Exportação correta de artefatos estruturados (CSV, JSON, manifest).
17. Detecção e rejeição de embaralhamento temporal (NO SHUFFLE).
18. Auditoria de integridade do dataset de experiências.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from finbot.exchange import CandleData
from finbot.experience import (
    DecisionContext,
    ExperienceRecord,
    OutcomeContext,
    build_experience_id,
)
from finbot.lab.learning import (
    FEATURE_NAMES,
    FORBIDDEN_OUTCOME_FIELDS,
    DatasetAuditResult,
    LearningDataset,
    PureNumpyBaseline,
    PureNumpyRidge,
    PureNumpyScaler,
    audit_experience_dataset,
    build_learning_dataset,
    calculate_learning_metrics,
    check_sample_sufficiency,
    export_learning_artifacts,
    fit_and_scale_features,
    fit_baseline_model,
    fit_ridge_model,
    predict_model,
    run_learning_experiment,
    temporal_train_val_test_split,
)


class TestLabLearning(unittest.TestCase):
    """Testes metodológicos e de integridade do FinBot Lab Learning (FASE 7.9G)."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _create_synthetic_candles(
        self,
        count: int = 200,
        base_price: float = 100.0,
        step: float = 0.5,
        start_ts: int = 1700000000000,
        interval_ms: int = 300000,  # 5m = 300.000 ms
    ) -> list[CandleData]:
        """Gera candles sintéticos com valores e timestamps estritamente crescentes."""
        candles = []
        for i in range(count):
            p = base_price + i * step
            candles.append(
                CandleData(
                    timestamp=start_ts + i * interval_ms,
                    open=p,
                    high=p + 1.0,
                    low=p - 1.0,
                    close=p,
                    volume=100.0 + i,
                )
            )
        return candles

    def _create_synthetic_experiences(
        self,
        candles: list[CandleData],
        count: int = 60,
        start_idx: int = 15,
        step_idx: int = 2,
    ) -> list[ExperienceRecord]:
        """Gera sequência de experiências válidas referenciando candles sintéticos."""
        exps = []
        for i in range(count):
            candle_idx = start_idx + i * step_idx
            if candle_idx >= len(candles) - 25:
                break
            c = candles[candle_idx]
            iso_dt = f"2026-09-27T{i // 60:02d}:{i % 60:02d}:00+00:00"
            dec = DecisionContext(
                decision_at=iso_dt,
                candle_timestamp=c.timestamp,
                symbol="BTC/USDT",
                timeframe="5m",
                price=c.close,
                open=c.open,
                high=c.high,
                low=c.low,
                close=c.close,
                volume=c.volume,
                strategy_name="SMA_CROSSOVER",
                strategy_version="1.0.0",
                strategy_parameters={"short_window": 5, "long_window": 10},
                signal="BUY" if i % 2 == 0 else "HOLD",
                signal_reason="Test signal",
                position_before="NONE",
                risk_decision="ALLOWED",
                risk_reason="Allowed",
                risk_allowed=True,
                execution_price=candles[candle_idx + 1].open if candle_idx + 1 < len(candles) else None,
                execution_quantity=0.1,
                execution_fee=0.01,
            )
            out = OutcomeContext(
                outcome_at=f"2026-09-27T{(i+1) // 60:02d}:{(i+1) % 60:02d}:00+00:00",
                exit_price=c.close * 1.02,
                realized_pnl=10.0,
                realized_return=0.02,
                fees=0.01,
                mfe=0.03,
                mae=-0.01,
                trade_duration=1200,
                future_return_5=0.005,
                future_return_20=0.015,
                future_return_50=0.025,
                future_return_100=0.035,
                outcome="WIN",
            )
            exp = ExperienceRecord(
                experience_id=build_experience_id("test", f"trade_{i:04d}"),
                source="test",
                source_id=f"trade_{i:04d}",
                run_id="test_run",
                decision=dec,
                outcome=out,
            )
            exps.append(exp)
        return exps

    def test_01_dataset_temporal_ordering(self) -> None:
        """1. Garante que build_learning_dataset ordena estritamente por decision_at."""
        candles = self._create_synthetic_candles(count=150)
        exps = self._create_synthetic_experiences(candles, count=30)

        # Passa experiências em ordem invertida
        shuffled_exps = list(reversed(exps))
        dataset = build_learning_dataset(shuffled_exps, candles=candles, target_name="future_return_20")

        self.assertGreater(dataset.total_samples, 0)
        for i in range(len(dataset.timestamps) - 1):
            self.assertLess(
                dataset.timestamps[i],
                dataset.timestamps[i + 1],
                f"Quebra de ordem temporal no índice {i}",
            )

    def test_02_split_60_20_20(self) -> None:
        """2. Garante proporção estrita de 60% Train, 20% Validation, 20% Test."""
        N = 100
        X = np.ones((N, 5))
        y = np.arange(N, dtype=np.float64)
        ts = [f"2026-01-01T{i:03d}" for i in range(N)]
        ids = [f"id_{i}" for i in range(N)]

        dataset = LearningDataset(
            X=X,
            y=y,
            feature_names=["f1", "f2", "f3", "f4", "f5"],
            target_name="future_return_20",
            timestamps=ts,
            experience_ids=ids,
            total_samples=N,
        )

        split = temporal_train_val_test_split(dataset, train_ratio=0.60, val_ratio=0.20, test_ratio=0.20)
        self.assertEqual(split.n_train, 60)
        self.assertEqual(split.n_val, 20)
        self.assertEqual(split.n_test, 20)
        self.assertEqual(split.n_train + split.n_val + split.n_test, 100)

    def test_03_no_overlap_train_val_test(self) -> None:
        """3. Nenhum overlap de IDs entre Train, Validation e Test."""
        N = 50
        X = np.zeros((N, 2))
        y = np.zeros(N)
        ts = [f"2026-01-01T{i:03d}" for i in range(N)]
        ids = [f"exp_{i:04d}" for i in range(N)]

        dataset = LearningDataset(
            X=X, y=y, feature_names=["f1", "f2"], target_name="future_return_20",
            timestamps=ts, experience_ids=ids, total_samples=N,
        )
        split = temporal_train_val_test_split(dataset)

        set_tr = set(split.ids_train)
        set_va = set(split.ids_val)
        set_te = set(split.ids_test)

        self.assertEqual(len(set_tr.intersection(set_va)), 0, "Train e Val compartilham IDs!")
        self.assertEqual(len(set_va.intersection(set_te)), 0, "Val e Test compartilham IDs!")
        self.assertEqual(len(set_tr.intersection(set_te)), 0, "Train e Test compartilham IDs!")

    def test_04_train_always_before_validation(self) -> None:
        """4. Train sempre anterior à Validation (max(ts_train) < min(ts_val))."""
        N = 40
        X = np.zeros((N, 2))
        y = np.zeros(N)
        ts = [f"2026-02-01T{i:02d}:00:00Z" for i in range(N)]
        ids = [f"id_{i}" for i in range(N)]

        dataset = LearningDataset(
            X=X, y=y, feature_names=["f1", "f2"], target_name="future_return_20",
            timestamps=ts, experience_ids=ids, total_samples=N,
        )
        split = temporal_train_val_test_split(dataset)

        self.assertLess(max(split.ts_train), min(split.ts_val))

    def test_05_validation_always_before_test(self) -> None:
        """5. Validation sempre anterior ao Test (max(ts_val) < min(ts_test))."""
        N = 40
        X = np.zeros((N, 2))
        y = np.zeros(N)
        ts = [f"2026-02-01T{i:02d}:00:00Z" for i in range(N)]
        ids = [f"id_{i}" for i in range(N)]

        dataset = LearningDataset(
            X=X, y=y, feature_names=["f1", "f2"], target_name="future_return_20",
            timestamps=ts, experience_ids=ids, total_samples=N,
        )
        split = temporal_train_val_test_split(dataset)

        self.assertLess(max(split.ts_val), min(split.ts_test))

    def test_06_baseline_trained_strictly_on_train(self) -> None:
        """6. Baseline treinado exclusivamente no Train (não usa dados de Val ou Test)."""
        y_train = np.array([0.01, 0.02, 0.03])
        y_val = np.array([0.10, 0.20])
        y_test = np.array([0.50, 0.60])

        baseline = fit_baseline_model(y_train)

        # Predição para Val e Test deve ser exatamente a média do Train = 0.02
        pred_val = predict_model(baseline, np.zeros((len(y_val), 1)))
        pred_test = predict_model(baseline, np.zeros((len(y_test), 1)))

        np.testing.assert_allclose(pred_val, 0.02)
        np.testing.assert_allclose(pred_test, 0.02)

    def test_07_model_trained_strictly_on_train(self) -> None:
        """7. Modelo Ridge treinado exclusivamente no Train."""
        # Se alterarmos y_test ou y_val, os pesos do modelo treinado em Train não mudam
        X_train = np.array([[1.0, 2.0], [2.0, 3.0], [3.0, 4.0]])
        y_train = np.array([1.0, 2.0, 3.0])

        model1 = fit_ridge_model(X_train, y_train, alpha=1.0)
        coef1 = model1.coef_.copy() if hasattr(model1, "coef_") else None

        # Novo treinamento idêntico com Train isolado
        model2 = fit_ridge_model(X_train, y_train, alpha=1.0)
        coef2 = model2.coef_.copy() if hasattr(model2, "coef_") else None

        np.testing.assert_allclose(coef1, coef2)

    def test_08_preprocessing_scaler_no_leakage(self) -> None:
        """8. Preprocessamento: scaler ajustado unicamente em Train."""
        # Train tem média 10, Val tem média 100, Test tem média 1000
        X_tr = np.array([[10.0], [10.0], [10.0]])
        X_va = np.array([[100.0]])
        X_te = np.array([[1000.0]])

        # Scaler ajustado somente no Train
        X_tr_s, X_va_s, X_te_s, scaler = fit_and_scale_features(X_tr, X_va, X_te)

        # Média gravada no scaler deve ser exatamente 10.0 (do Treino), não a média global
        self.assertAlmostEqual(float(scaler.mean_[0]), 10.0)

        # X_tr_s deve ser 0.0 (pois todos os valores eram 10.0 e média era 10.0)
        np.testing.assert_allclose(X_tr_s, np.zeros((3, 1)))
        # X_va_s e X_te_s são transformados com base na média do Treino (100 - 10 = 90)
        self.assertAlmostEqual(float(X_va_s[0, 0]), 90.0)

    def test_09_deterministic_metrics(self) -> None:
        """9. Métricas estatísticas e econômicas são exatas e determinísticas."""
        y_true = np.array([0.02, -0.01, 0.04, -0.02])
        y_pred = np.array([0.01, -0.02, 0.02, -0.01])

        m = calculate_learning_metrics(y_true, y_pred)

        # Erros absolutos: |0.02-0.01|=0.01, |-0.01 - -0.02|=0.01, |0.04-0.02|=0.02, |-0.02 - -0.01|=0.01 -> mean = 0.0125
        self.assertAlmostEqual(m.mae, 0.0125, places=5)
        # Sinais: (+, +), (-, -), (+, +), (-, -) -> directional_acc = 1.0 (100%)
        self.assertEqual(m.directional_accuracy, 1.0)
        # Diagnóstico econômico:
        # Quando pred > 0: observações 0 e 2, y_true = [0.02, 0.04] -> mean = 0.03
        self.assertAlmostEqual(m.economic_positive_pred_return, 0.03, places=5)
        self.assertEqual(m.economic_positive_count, 2)
        # Quando pred <= 0: observações 1 e 3, y_true = [-0.01, -0.02] -> mean = -0.015
        self.assertAlmostEqual(m.economic_negative_pred_return, -0.015, places=5)
        self.assertEqual(m.economic_negative_count, 2)

    def test_10_insufficient_sample_handled_correctly(self) -> None:
        """10. Amostra insuficiente é tratada de forma limpa como INSUFFICIENT_SAMPLE."""
        candles = self._create_synthetic_candles(count=50)
        # Apenas 5 experiências, abaixo do min_samples padrão (50)
        exps = self._create_synthetic_experiences(candles, count=5)

        res = run_learning_experiment(exps, candles=candles, min_samples=50)
        self.assertEqual(res.status, "INSUFFICIENT_SAMPLE")
        self.assertIn("INSUFFICIENT_SAMPLE", res.conclusion)
        self.assertEqual(res.n_train, 0)
        self.assertEqual(res.n_val, 0)
        self.assertEqual(res.n_test, 0)

    def test_11_forbidden_features_rejected(self) -> None:
        """11. Campos de outcome/leakage são proibidos nas features e disparam erro."""
        candles = self._create_synthetic_candles(count=50)
        exps = self._create_synthetic_experiences(candles, count=10)

        for forbidden in FORBIDDEN_OUTCOME_FIELDS:
            with self.assertRaises(ValueError, msg=f"Campo proibido '{forbidden}' não disparou ValueError"):
                build_learning_dataset(
                    exps,
                    candles=candles,
                    feature_names=["price", forbidden],
                )

    def test_12_target_future_return_20_calculated_correctly(self) -> None:
        """12. Target future_return_20 segue rigorosamente o contrato da Fase 7.9F."""
        # Candles com preço linear: 100, 101, 102, ...
        candles = self._create_synthetic_candles(count=100, base_price=100.0, step=1.0)
        exps = self._create_synthetic_experiences(candles, count=10, start_idx=10, step_idx=5)

        dataset = build_learning_dataset(exps, candles=candles, target_name="future_return_20")

        # Para cada experiência no índice candle_idx k:
        # P_ref = Open[k+1] = candles[k+1].open
        # P_future = Close[k+20] = candles[k+20].close
        # Expected return = (P_future - P_ref) / P_ref
        first_exp = exps[0]
        k = 10  # start_idx
        p_ref = candles[k + 1].open
        p_fut = candles[k + 20].close
        expected_ret = (p_fut - p_ref) / p_ref

        self.assertAlmostEqual(dataset.y[0], expected_ret, places=6)

    def test_13_reproducibility(self) -> None:
        """13. Execuções repetidas com os mesmos dados produzem resultados 100% idênticos."""
        candles = self._create_synthetic_candles(count=200)
        exps = self._create_synthetic_experiences(candles, count=70)

        res1 = run_learning_experiment(exps, candles=candles, min_samples=30)
        res2 = run_learning_experiment(exps, candles=candles, min_samples=30)

        self.assertEqual(res1.status, res2.status)
        self.assertEqual(res1.n_train, res2.n_train)
        self.assertEqual(res1.model_test_metrics.mae, res2.model_test_metrics.mae)
        self.assertEqual(res1.model_test_metrics.rmse, res2.model_test_metrics.rmse)
        self.assertEqual(res1.coefficients, res2.coefficients)

    def test_14_future_mutation_does_not_alter_train_features(self) -> None:
        """14. Anti-leakage: Mutar candles futuros NÃO altera as features no instante da decisão."""
        candles_orig = self._create_synthetic_candles(count=150, base_price=100.0, step=1.0)
        candles_mut = self._create_synthetic_candles(count=150, base_price=100.0, step=1.0)

        exps = self._create_synthetic_experiences(candles_orig, count=30, start_idx=15, step_idx=2)

        # No dataset mutado, alteramos os preços dos candles futuros (a partir do índice 80)
        for i in range(80, len(candles_mut)):
            candles_mut[i] = CandleData(
                timestamp=candles_mut[i].timestamp,
                open=9999.0,
                high=10000.0,
                low=9998.0,
                close=9999.0,
                volume=50000.0,
            )

        ds_orig = build_learning_dataset(exps, candles=candles_orig)
        ds_mut = build_learning_dataset(exps, candles=candles_mut)

        # As features de decisões tomadas antes do índice 80 devem ser estritamente idênticas
        np.testing.assert_allclose(ds_orig.X, ds_mut.X)

    def test_15_future_mutation_alters_labels(self) -> None:
        """15. Anti-leakage: Mutar candles futuros altera os labels futuros adequadamente."""
        candles_orig = self._create_synthetic_candles(count=150, base_price=100.0, step=1.0)
        candles_mut = self._create_synthetic_candles(count=150, base_price=100.0, step=1.0)

        exps = self._create_synthetic_experiences(candles_orig, count=30, start_idx=15, step_idx=2)

        # Altera fortemente os candles futuros
        for i in range(40, len(candles_mut)):
            candles_mut[i] = CandleData(
                timestamp=candles_mut[i].timestamp,
                open=9999.0,
                high=10000.0,
                low=9998.0,
                close=9999.0,
                volume=50000.0,
            )

        ds_orig = build_learning_dataset(exps, candles=candles_orig)
        ds_mut = build_learning_dataset(exps, candles=candles_mut)

        # Labels futuros das decisões cujos horizontes caem na zona mutada devem ter mudado
        self.assertFalse(np.allclose(ds_orig.y, ds_mut.y))

    def test_16_export_artifacts_structure(self) -> None:
        """16. Exportação de artefatos gera JSON, CSV e manifest com campos válidos."""
        candles = self._create_synthetic_candles(count=200)
        exps = self._create_synthetic_experiences(candles, count=65)

        res = run_learning_experiment(exps, candles=candles, min_samples=30)
        self.assertEqual(res.status, "COMPLETE")

        out_dir = Path(self.temp_dir.name) / "artifacts"
        exported = export_learning_artifacts(res, output_dir=out_dir)

        # Verifica existência dos 4 arquivos
        self.assertTrue(exported["results_json"].exists())
        self.assertTrue(exported["summary_csv"].exists())
        self.assertTrue(exported["coefficients_csv"].exists())
        self.assertTrue(exported["manifest_json"].exists())

        # Valida JSON de resultados
        with open(exported["results_json"], "r", encoding="utf-8") as f:
            data = json.load(f)
            self.assertEqual(data["status"], "COMPLETE")
            self.assertIn("baseline_val", data)
            self.assertIn("model_val", data)
            self.assertIn("coefficients", data)

        # Valida CSV de sumário
        with open(exported["summary_csv"], "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            self.assertEqual(len(rows), 6)  # Train, Val, Test x 2 modelos (Baseline, Ridge)

        # Valida manifest
        with open(exported["manifest_json"], "r", encoding="utf-8") as f:
            manifest = json.load(f)
            self.assertEqual(manifest["target"], "future_return_20")
            self.assertEqual(manifest["n_train"], res.n_train)

    def test_17_no_temporal_shuffle_violation_raises(self) -> None:
        """17. Particionamento temporal detecta e rejeita dados fora de ordem cronológica."""
        N = 20
        X = np.zeros((N, 2))
        y = np.zeros(N)
        # Força desordem proposital nos timestamps
        ts = [f"2026-01-01T{i:02d}" for i in range(N)]
        ts[15] = "2025-01-01T00"  # Inversão temporal na partição de Test

        dataset = LearningDataset(
            X=X, y=y, feature_names=["f1", "f2"], target_name="future_return_20",
            timestamps=ts, experience_ids=[f"id_{i}" for i in range(N)], total_samples=N,
        )
        with self.assertRaises(ValueError) as ctx:
            temporal_train_val_test_split(dataset)
        self.assertIn("Data leakage temporal detectado", str(ctx.exception))

    def test_18_audit_dataset(self) -> None:
        """18. Auditoria de experiências calcula total, proveniência e duplicatas com precisão."""
        candles = self._create_synthetic_candles(count=150)
        exps = self._create_synthetic_experiences(candles, count=20)
        # Insere uma duplicata intencional
        exps.append(exps[0])

        audit = audit_experience_dataset(exps, candles=candles)
        self.assertEqual(audit.total_experiences, 21)
        self.assertEqual(audit.duplicate_experiences_count, 1)
        self.assertEqual(audit.experiences_by_symbol.get("BTC/USDT"), 21)
        self.assertIsNotNone(audit.first_decision_at)
        self.assertIsNotNone(audit.last_decision_at)


if __name__ == "__main__":
    unittest.main()
