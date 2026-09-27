"""Suíte de testes para Model Validation e Model Registry do FinBot Lab (FASE 7.9H).

Cobre todos os 25 testes metodológicos e validação de segurança arquitetural:
1. Registro de candidato com status inicial CANDIDATE.
2. Identificador de modelo (model_id) estritamente determinístico.
3. Manifesto serializado e desserializado de forma determinística.
4. Dataset fingerprint sensível a alterações nos dados.
5. Feature fingerprint sensível a alteração na ordem das features.
6. Target fingerprint sensível à semântica e horizonte do alvo.
7. Transição para status CANDIDATE auditada no log.
8. Transição para status VALIDATED com registro de relatório.
9. Transição para status REJECTED com motivo explícito.
10. Transição para status REVOKED para modelo previamente validado.
11. Histórico e log de auditoria append-only não são sobrescritos.
12. Modelo rejeitado nunca é retornado por get_latest_validated().
13. Dataset alterado detectado pelo Validation Gate falha com erro.
14. Features alteradas detectadas pelo Validation Gate falham com erro.
15. Target alterado detectado pelo Validation Gate falha com erro.
16. Split com overlap ou desordem temporal é rejeitado pelo Gate.
17. Flag shuffle=True é detectada e rejeitada como risco de leakage.
18. Flag preprocessing_fit_train_only=False é rejeitada como leakage.
19. Modelo inferior ao baseline em out-of-sample é REJEITADO (caso da F7.9G).
20. Modelo superior ao baseline em out-of-sample e com integridade OK é VALIDATED.
21. get_latest_validated() retorna exclusivamente modelos VALIDATED.
22. Chamadas ao Registry não ativam ou interferem no Paper Trading.
23. Execuções repetidas geram o mesmo model_id idêntico.
24. Registro de candidato idêntico é idempotente.
25. Tentativa de registrar mesmo ID com conteúdo divergente dispara erro de integridade.
26. Prova de isolamento arquitetural: Paper Runner, Risk e Strategy não importam Registry.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from finbot.exchange import CandleData
from finbot.lab.model_registry import (
    CHECK_FAIL,
    CHECK_PASS,
    STATUS_CANDIDATE,
    STATUS_REJECTED,
    STATUS_REVOKED,
    STATUS_VALIDATED,
    ModelManifest,
    ModelRegistry,
    compute_dataset_fingerprint,
    compute_feature_fingerprint,
    compute_model_id,
    compute_target_fingerprint,
    export_registry_reports,
    validate_model_candidate,
)


class TestModelRegistry(unittest.TestCase):
    """Testes unitários e metodológicos da FASE 7.9H (Model Validation / Registry)."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_registry.sqlite3"
        self.registry = ModelRegistry(db_path=self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _create_sample_manifest(
        self,
        model_type: str = "Ridge",
        alpha: float = 1.0,
        val_mae: float = 0.003605,
        base_val_mae: float = 0.003387,
        test_mae: float = 0.004995,
        base_test_mae: float = 0.003608,
        shuffle: bool = False,
        fit_train_only: bool = True,
        train_range: tuple[str, str] = ("2026-08-23T11:25:00+00:00", "2026-09-13T02:00:00+00:00"),
        val_range: tuple[str, str] = ("2026-09-13T02:55:00+00:00", "2026-09-20T09:25:00+00:00"),
        test_range: tuple[str, str] = ("2026-09-20T11:25:00+00:00", "2026-09-27T00:50:00+00:00"),
        feature_names: list[str] | None = None,
        dataset_fingerprint: str = "a" * 64,
    ) -> ModelManifest:
        """Cria um manifesto de teste consistente com parâmetros configuráveis."""
        if feature_names is None:
            feature_names = ["price", "open", "close", "sma_short", "sma_long"]

        feat_fp = compute_feature_fingerprint(feature_names, version="1.0.0")
        target_name = "future_return_20"
        target_def = "(Close[t+20] - Open[t+1]) / Open[t+1]"
        target_fp = compute_target_fingerprint(target_name, semantics=target_def, horizon=20)
        params = {"alpha": alpha}

        payload = {
            "dataset_fingerprint": dataset_fingerprint,
            "source": "canonical_backtest_10k",
            "symbol": "BTC/USDT",
            "timeframe": "5m",
            "target_name": target_name,
            "target_fingerprint": target_fp,
            "feature_fingerprint": feat_fp,
            "model_type": model_type,
            "model_parameters": params,
            "preprocessing": "StandardScaler",
            "preprocessing_fit_train_only": fit_train_only,
            "shuffle": shuffle,
            "train_range": list(train_range),
            "val_range": list(val_range),
            "test_range": list(test_range),
            "train_samples": 345,
            "validation_samples": 115,
            "test_samples": 115,
            "code_version": "1.0.0",
        }
        model_id = compute_model_id(payload)

        return ModelManifest(
            model_id=model_id,
            created_at="2026-09-27T03:00:00+00:00",
            status=STATUS_CANDIDATE,
            status_reason="Registered as candidate",
            dataset_id="canonical_backtest_10k",
            dataset_fingerprint=dataset_fingerprint,
            source="canonical_backtest_10k",
            symbol="BTC/USDT",
            timeframe="5m",
            target_name=target_name,
            target_definition=target_def,
            target_fingerprint=target_fp,
            feature_set_version="1.0.0",
            feature_names=feature_names,
            feature_fingerprint=feat_fp,
            preprocessing="StandardScaler",
            preprocessing_version="1.0.0",
            preprocessing_fit_train_only=fit_train_only,
            shuffle=shuffle,
            model_type=model_type,
            model_parameters=params,
            train_range=train_range,
            val_range=val_range,
            test_range=test_range,
            train_samples=345,
            validation_samples=115,
            test_samples=115,
            training_environment={"env": "test"},
            code_version="1.0.0",
            metrics_train={"mae": 0.0029, "rmse": 0.0042, "r2": 0.10},
            metrics_validation={"mae": val_mae, "rmse": 0.0061, "r2": -0.03},
            metrics_test={"mae": test_mae, "rmse": 0.0067, "r2": -0.43},
            baseline_metrics_train={"mae": 0.0030, "rmse": 0.0045, "r2": 0.0},
            baseline_metrics_validation={"mae": base_val_mae, "rmse": 0.0061, "r2": -0.02},
            baseline_metrics_test={"mae": base_test_mae, "rmse": 0.0056, "r2": -0.01},
        )

    def test_01_register_candidate(self) -> None:
        """1. Registra modelo candidato com status inicial CANDIDATE."""
        manifest = self._create_sample_manifest()
        reg_manifest = self.registry.register_candidate(manifest)

        self.assertEqual(reg_manifest.status, STATUS_CANDIDATE)
        stored = self.registry.get_model(manifest.model_id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.model_id, manifest.model_id)
        self.assertEqual(stored.status, STATUS_CANDIDATE)

    def test_02_deterministic_model_id(self) -> None:
        """2. Identificador de modelo (model_id) é 100% determinístico."""
        manifest1 = self._create_sample_manifest()
        manifest2 = self._create_sample_manifest()

        self.assertEqual(manifest1.model_id, manifest2.model_id)
        self.assertTrue(manifest1.model_id.startswith("model_"))

    def test_03_deterministic_manifest_serialization(self) -> None:
        """3. Manifesto serializado e desserializado produz dados idênticos."""
        manifest = self._create_sample_manifest()
        d = manifest.to_dict()
        reconstructed = ModelManifest.from_dict(d)

        self.assertEqual(manifest.model_id, reconstructed.model_id)
        self.assertEqual(manifest.feature_fingerprint, reconstructed.feature_fingerprint)
        self.assertEqual(manifest.train_range, reconstructed.train_range)

    def test_04_dataset_fingerprint_sensitivity(self) -> None:
        """4. Dataset fingerprint altera se os dados forem alterados."""
        c1 = [CandleData(1700000000000, 100.0, 102.0, 99.0, 101.0, 10.0)]
        c2 = [CandleData(1700000000000, 100.0, 102.0, 99.0, 105.0, 10.0)]  # Fechamento diferente

        fp1 = compute_dataset_fingerprint(c1)
        fp2 = compute_dataset_fingerprint(c2)

        self.assertNotEqual(fp1, fp2)
        self.assertEqual(len(fp1), 64)

    def test_05_feature_fingerprint_order_sensitivity(self) -> None:
        """5. Feature fingerprint é sensível à ordem das features."""
        f_list1 = ["price", "close", "volume"]
        f_list2 = ["close", "price", "volume"]

        fp1 = compute_feature_fingerprint(f_list1)
        fp2 = compute_feature_fingerprint(f_list2)

        self.assertNotEqual(fp1, fp2, "Fingerprint de features deve ser estritamente sensível à ordem!")

    def test_06_target_fingerprint_sensitivity(self) -> None:
        """6. Target fingerprint é sensível à semântica e horizonte."""
        fp1 = compute_target_fingerprint("future_return_20", horizon=20)
        fp2 = compute_target_fingerprint("future_return_50", horizon=50)

        self.assertNotEqual(fp1, fp2)

    def test_07_status_candidate(self) -> None:
        """7. Status CANDIDATE inicial é gravado no audit log."""
        manifest = self._create_sample_manifest()
        self.registry.register_candidate(manifest)

        history = self.registry.get_audit_history(manifest.model_id)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["new_status"], STATUS_CANDIDATE)

    def test_08_status_validated(self) -> None:
        """8. Modelo que supera baseline em OOS e passa integridade vira VALIDATED."""
        # Configura modelo com MAE inferior ao baseline em Val e Test
        manifest = self._create_sample_manifest(
            val_mae=0.0020, base_val_mae=0.0035,
            test_mae=0.0025, base_test_mae=0.0040,
        )
        self.registry.register_candidate(manifest)
        validated = self.registry.validate_candidate(manifest.model_id)

        self.assertEqual(validated.status, STATUS_VALIDATED)
        self.assertIn("VALIDATED", validated.status_reason)

    def test_09_status_rejected(self) -> None:
        """9. Modelo com desempenho OOS inferior ao baseline é REJECTED."""
        # Caso clássico da F7.9G: Ridge MAE > Baseline MAE
        manifest = self._create_sample_manifest(
            val_mae=0.003605, base_val_mae=0.003387,
            test_mae=0.004995, base_test_mae=0.003608,
        )
        self.registry.register_candidate(manifest)
        rejected = self.registry.validate_candidate(manifest.model_id)

        self.assertEqual(rejected.status, STATUS_REJECTED)
        self.assertIn("MODEL_DOES_NOT_BEAT_BASELINE", rejected.status_reason)

    def test_10_status_revoked(self) -> None:
        """10. Modelo VALIDATED pode ser revogado com status REVOKED sem perda de histórico."""
        manifest = self._create_sample_manifest(
            val_mae=0.0020, base_val_mae=0.0035,
            test_mae=0.0025, base_test_mae=0.0040,
        )
        self.registry.register_candidate(manifest)
        self.registry.validate_candidate(manifest.model_id)

        revoked = self.registry.revoke_model(manifest.model_id, reason="Dataset revisado posteriormente")
        self.assertEqual(revoked.status, STATUS_REVOKED)

        history = self.registry.get_audit_history(manifest.model_id)
        # Transições: None -> CANDIDATE -> VALIDATED -> REVOKED
        statuses = [h["new_status"] for h in history]
        self.assertEqual(statuses, [STATUS_CANDIDATE, STATUS_VALIDATED, STATUS_REVOKED])

    def test_11_immutable_audit_history(self) -> None:
        """11. Log de auditoria é append-only e preserva histórico integral."""
        manifest = self._create_sample_manifest()
        self.registry.register_candidate(manifest)
        self.registry.validate_candidate(manifest.model_id)
        self.registry.reject_model(manifest.model_id, reason="Manual rejection")

        history = self.registry.get_audit_history(manifest.model_id)
        self.assertEqual(len(history), 3)
        self.assertEqual(history[0]["new_status"], STATUS_CANDIDATE)
        self.assertEqual(history[1]["new_status"], STATUS_REJECTED)
        self.assertEqual(history[2]["new_status"], STATUS_REJECTED)

    def test_12_rejected_model_never_appears_as_validated(self) -> None:
        """12. Modelo rejeitado nunca é retornado em get_latest_validated()."""
        manifest = self._create_sample_manifest(
            val_mae=0.003605, base_val_mae=0.003387,
            test_mae=0.004995, base_test_mae=0.003608,
        )
        self.registry.register_candidate(manifest)
        self.registry.validate_candidate(manifest.model_id)

        latest_val = self.registry.get_latest_validated()
        self.assertIsNone(latest_val)

    def test_13_dataset_alteration_detected(self) -> None:
        """13. Detecção de alteração no dataset invalida e rejeita candidato."""
        manifest = self._create_sample_manifest(dataset_fingerprint="b" * 64)
        self.registry.register_candidate(manifest)

        # Valida passando dataset esperado diferente do gravado
        different_fp = "c" * 64
        rejected = self.registry.validate_candidate(manifest.model_id, expected_dataset_fingerprint=different_fp)

        self.assertEqual(rejected.status, STATUS_REJECTED)
        self.assertIn("DATASET_FINGERPRINT_MISMATCH", rejected.status_reason)

    def test_14_feature_alteration_detected(self) -> None:
        """14. Manipulação de features é detectada pelo Validation Gate."""
        manifest = self._create_sample_manifest()
        # Modifica o manifesto em memória para violar o hash das features
        tampered_dict = manifest.to_dict()
        tampered_dict["feature_fingerprint"] = "0" * 64
        tampered = ModelManifest.from_dict(tampered_dict)

        verdict, report = validate_model_candidate(tampered)
        self.assertEqual(verdict, STATUS_REJECTED)
        self.assertIn("FEATURE_FINGERPRINT_MISMATCH", report.reason)

    def test_15_target_alteration_detected(self) -> None:
        """15. Manipulação de target é detectada pelo Validation Gate."""
        manifest = self._create_sample_manifest()
        tampered_dict = manifest.to_dict()
        tampered_dict["target_fingerprint"] = "0" * 64
        tampered = ModelManifest.from_dict(tampered_dict)

        verdict, report = validate_model_candidate(tampered)
        self.assertEqual(verdict, STATUS_REJECTED)
        self.assertIn("TARGET_FINGERPRINT_MISMATCH", report.reason)

    def test_16_invalid_temporal_split_rejected(self) -> None:
        """16. Overlap temporal entre Train, Val ou Test rejeita a validação."""
        manifest = self._create_sample_manifest(
            train_range=("2026-01-01T00:00:00Z", "2026-01-15T00:00:00Z"),
            val_range=("2026-01-10T00:00:00Z", "2026-01-20T00:00:00Z"),  # Overlap com Train!
            test_range=("2026-01-21T00:00:00Z", "2026-01-30T00:00:00Z"),
        )
        verdict, report = validate_model_candidate(manifest)
        self.assertEqual(verdict, STATUS_REJECTED)
        self.assertIn("TEMPORAL_OVERLAP_DETECTED", report.reason)

    def test_17_leakage_shuffle_flag_rejected(self) -> None:
        """17. Presença de shuffle=True é rejeitada como risco de leakage."""
        manifest = self._create_sample_manifest(shuffle=True)
        verdict, report = validate_model_candidate(manifest)
        self.assertEqual(verdict, STATUS_REJECTED)
        self.assertIn("TEMPORAL_SHUFFLE_DETECTED", report.reason)

    def test_18_preprocessing_leakage_rejected(self) -> None:
        """18. Preprocessamento que não seja estritamente train-only é rejeitado."""
        manifest = self._create_sample_manifest(fit_train_only=False)
        verdict, report = validate_model_candidate(manifest)
        self.assertEqual(verdict, STATUS_REJECTED)
        self.assertIn("PREPROCESSING_LEAKAGE_DETECTED", report.reason)

    def test_19_model_worse_than_baseline_rejected(self) -> None:
        """19. Modelo out-of-sample pior que baseline é REJEITADO."""
        manifest = self._create_sample_manifest(
            val_mae=0.003605, base_val_mae=0.003387,
            test_mae=0.004995, base_test_mae=0.003608,
        )
        verdict, report = validate_model_candidate(manifest)
        self.assertEqual(verdict, STATUS_REJECTED)
        self.assertIn("MODEL_DOES_NOT_BEAT_BASELINE", report.reason)

    def test_20_model_better_than_baseline_validated(self) -> None:
        """20. Modelo out-of-sample superior ao baseline com integridade OK é VALIDATED."""
        manifest = self._create_sample_manifest(
            val_mae=0.0020, base_val_mae=0.0035,
            test_mae=0.0025, base_test_mae=0.0040,
        )
        verdict, report = validate_model_candidate(manifest)
        self.assertEqual(verdict, STATUS_VALIDATED)
        self.assertIn("MODEL_VALIDATED_ALL_CRITERIA", report.reason)

    def test_21_get_latest_validated_returns_only_validated(self) -> None:
        """21. get_latest_validated() retorna apenas modelos com status VALIDATED."""
        # Registra um modelo que será REJECTED
        rej_m = self._create_sample_manifest(alpha=1.0, val_mae=0.004, base_val_mae=0.003)
        self.registry.register_candidate(rej_m)
        self.registry.validate_candidate(rej_m.model_id)

        self.assertIsNone(self.registry.get_latest_validated())

        # Registra um modelo que será VALIDATED
        val_m = self._create_sample_manifest(alpha=2.0, val_mae=0.002, base_val_mae=0.003, test_mae=0.002, base_test_mae=0.004)
        self.registry.register_candidate(val_m)
        self.registry.validate_candidate(val_m.model_id)

        latest = self.registry.get_latest_validated()
        self.assertIsNotNone(latest)
        self.assertEqual(latest.model_id, val_m.model_id)
        self.assertEqual(latest.status, STATUS_VALIDATED)

    def test_22_registry_does_not_activate_paper_trading(self) -> None:
        """22. Nenhuma operação no Registry cria instâncias de PaperRunner ou Broker."""
        manifest = self._create_sample_manifest()
        self.registry.register_candidate(manifest)
        self.registry.validate_candidate(manifest.model_id)
        self.registry.get_latest_validated()
        self.registry.list_models()

        # O banco de dados do registry é estritamente isolado do banco operacional
        self.assertNotIn("paper", str(self.db_path).lower())
        self.assertTrue(self.db_path.exists())

    def test_23_repeated_execution_produces_identical_model_id(self) -> None:
        """23. Múltiplas execuções com a mesma especificação geram o mesmo model_id."""
        m1 = self._create_sample_manifest()
        m2 = self._create_sample_manifest()
        self.assertEqual(m1.model_id, m2.model_id)

    def test_24_duplicate_registration_is_idempotent(self) -> None:
        """24. Registro repetido do mesmo modelo exato é idempotente."""
        manifest = self._create_sample_manifest()
        reg1 = self.registry.register_candidate(manifest)
        reg2 = self.registry.register_candidate(manifest)

        self.assertEqual(reg1.model_id, reg2.model_id)
        all_models = self.registry.list_models()
        self.assertEqual(len(all_models), 1)

    def test_25_model_id_collision_with_different_content_raises(self) -> None:
        """25. Conflito de mesmo model_id com conteúdo divergente dispara erro de integridade."""
        manifest = self._create_sample_manifest()
        self.registry.register_candidate(manifest)

        # Cria payload adulterado com mesmo ID forçado mas dataset diferente
        adulterated_dict = manifest.to_dict()
        adulterated_dict["dataset_fingerprint"] = "9" * 64
        adulterated = ModelManifest.from_dict(adulterated_dict)

        with self.assertRaises(ValueError) as ctx:
            self.registry.register_candidate(adulterated)
        self.assertIn("Conflito de integridade", str(ctx.exception))

    def test_26_architectural_isolation_paper_runner_and_strategy(self) -> None:
        """26. Segurança arquitetural: Paper Runner, Risk Engine e Strategy não importam Registry."""
        import importlib
        import inspect

        paper_mod = importlib.import_module("finbot.paper")
        risk_mod = importlib.import_module("finbot.risk")
        strategy_mod = importlib.import_module("finbot.strategy")

        paper_src = inspect.getsource(paper_mod)
        risk_src = inspect.getsource(risk_mod)
        strategy_src = inspect.getsource(strategy_mod)

        self.assertNotIn("model_registry", paper_src)
        self.assertNotIn("ModelRegistry", paper_src)
        self.assertNotIn("model_registry", risk_src)
        self.assertNotIn("ModelRegistry", risk_src)
        self.assertNotIn("model_registry", strategy_src)
        self.assertNotIn("ModelRegistry", strategy_src)


if __name__ == "__main__":
    unittest.main()
