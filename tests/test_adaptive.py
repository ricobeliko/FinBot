"""Suíte de testes para a FASE 7.9I — Adaptive Paper com Shadow Mode e Fallback.

Cobre todos os requisitos constitucionais e arquiteturais:
1. ADAPTIVE_MODE='off' por padrão: comportamento operacional idêntico ao Paper anterior.
2. Modelo real REJECTED (model_b3e792893e42fd40) é bloqueado com 'MODEL_REJECTED'.
3. Sem modelo configurado ('') produz fallback seguro com 'NO_MODEL_CONFIGURED'.
4. Modelo CANDIDATE é bloqueado com 'MODEL_NOT_VALIDATED'.
5. Modelo REVOKED é bloqueado com 'MODEL_REVOKED'.
6. Modelo inexistente é bloqueado com 'MODEL_NOT_FOUND'.
7. Manifest ou fingerprint adulterado falha com 'MODEL_INTEGRITY_FAILURE'.
8. Shadow Mode com fixture VALIDATED executa e grava predição sem alterar final_signal.
9. Shadow Mode detecta e sinaliza divergência entre estratégia e recomendação do modelo.
10. Adaptive Mode com fixture VALIDATED gera recomendação que guia sinal sob aprovação do Risk Engine.
11. Risk Engine é soberano: bloqueios de risco sobrepõem recomendação adaptativa (ex: MAX_POSITION).
12. Erro de inferência (NaN/Inf ou exceção) dispara fail-closed e fallback seguro.
13. Prova de segurança: nenhum modelo não validado alcança execução de ordens.
14. Acúmulo de predições e cálculo de métricas de Shadow Mode no SQLite.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import math
from pathlib import Path
import tempfile
import unittest

from finbot.adaptive import (
    MODE_ADAPTIVE,
    MODE_OFF,
    MODE_SHADOW,
    REC_LONG_BIAS,
    REC_NO_LONG_BIAS,
    AdaptivePredictionRecord,
    build_decision_features,
    evaluate_adaptive_cycle,
    load_validated_model,
    predict,
)
from finbot.config import Config
from finbot.exchange import CandleData
from finbot.lab.model_registry import (
    STATUS_CANDIDATE,
    STATUS_REJECTED,
    STATUS_REVOKED,
    STATUS_VALIDATED,
    ModelManifest,
    ModelRegistry,
    compute_feature_fingerprint,
    compute_model_id,
    compute_target_fingerprint,
)
from finbot.paper import execute_paper_cycle
from finbot.risk import RiskDecisionCode
from finbot.storage import PaperAccount, PaperPosition, PaperStorage
from finbot.strategy import Signal


def _make_closed_candles(
    prices: list[float],
    interval_ms: int = 60000,
    start_ts: int = 1700000000000,
) -> list[CandleData]:
    """Gera lista de candles sintéticos para testes."""
    candles = []
    for i, p in enumerate(prices):
        candles.append(
            CandleData(
                timestamp=start_ts + i * interval_ms,
                open=p,
                high=p * 1.01,
                low=p * 0.99,
                close=p,
                volume=10.0,
            )
        )
    return candles


class TestAdaptivePaper(unittest.TestCase):
    """Bateria de testes completa da FASE 7.9I (Adaptive Paper)."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.paper_db_path = Path(self.tmp_dir.name) / "test_paper.sqlite3"
        self.registry_db_path = Path(self.tmp_dir.name) / "test_registry.sqlite3"

        self.storage = PaperStorage(db_path=self.paper_db_path)
        self.storage.init_db(initial_cash=Decimal("10000.00"))

        self.registry = ModelRegistry(db_path=self.registry_db_path)

        self.config = Config(
            paper_initial_cash=10000.0,
            paper_trade_notional=100.0,
            paper_commission=0.001,
            paper_db_path=str(self.paper_db_path),
            paper_timeframe="1m",
            paper_candle_limit=20,
            short_window=5,
            long_window=10,
            adaptive_mode="off",
            adaptive_model_id="",
            adaptive_registry_db=str(self.registry_db_path),
        )

    def tearDown(self) -> None:
        try:
            self.tmp_dir.cleanup()
        except Exception:
            pass

    def _create_synthetic_model(
        self,
        status: str = STATUS_VALIDATED,
        tag: str = "default",
        model_type: str = "LinearModel",
        coefficients: dict[str, float] | None = None,
        intercept: float = 0.0,
    ) -> ModelManifest:
        """Cria e registra modelo sintético no registry temporário para testes."""
        feature_names = ["price", "open", "close", "sma_short", "sma_long"]
        feat_fp = compute_feature_fingerprint(feature_names, version="1.0.0")
        target_name = "future_return_20"
        target_def = "(Close[t+20] - Open[t+1]) / Open[t+1]"
        target_fp = compute_target_fingerprint(target_name, semantics=target_def, horizon=20)

        if coefficients is None:
            coefficients = {"price": 0.0001, "close": 0.0001}

        params = {
            "coefficients": coefficients,
            "intercept": intercept,
        }

        payload = {
            "dataset_fingerprint": "a" * 64,
            "source": f"synthetic_test_{tag}",
            "symbol": "BTC/USDT",
            "timeframe": "1m",
            "target_name": target_name,
            "target_fingerprint": target_fp,
            "feature_fingerprint": feat_fp,
            "model_type": model_type,
            "model_parameters": params,
            "preprocessing": "None",
            "preprocessing_fit_train_only": True,
            "shuffle": False,
            "train_range": ["2026-09-01T00:00:00+00:00", "2026-09-09T23:55:00+00:00"],
            "val_range": ["2026-09-10T00:00:00+00:00", "2026-09-14T23:55:00+00:00"],
            "test_range": ["2026-09-15T00:00:00+00:00", "2026-09-20T00:00:00+00:00"],
            "train_samples": 100,
            "validation_samples": 50,
            "test_samples": 50,
            "code_version": "1.0.0",
        }
        model_id = compute_model_id(payload)

        manifest = ModelManifest(
            model_id=model_id,
            created_at="2026-09-27T03:00:00+00:00",
            status=STATUS_CANDIDATE,
            status_reason="Registered as synthetic candidate",
            dataset_id="synthetic_100",
            dataset_fingerprint="a" * 64,
            source=f"synthetic_test_{tag}",
            symbol="BTC/USDT",
            timeframe="1m",
            target_name=target_name,
            target_definition=target_def,
            target_fingerprint=target_fp,
            feature_set_version="1.0.0",
            feature_names=feature_names,
            feature_fingerprint=feat_fp,
            preprocessing="None",
            preprocessing_version="1.0.0",
            preprocessing_fit_train_only=True,
            shuffle=False,
            model_type=model_type,
            model_parameters=params,
            train_range=("2026-09-01T00:00:00+00:00", "2026-09-09T23:55:00+00:00"),
            val_range=("2026-09-10T00:00:00+00:00", "2026-09-14T23:55:00+00:00"),
            test_range=("2026-09-15T00:00:00+00:00", "2026-09-20T00:00:00+00:00"),
            train_samples=100,
            validation_samples=50,
            test_samples=50,
            training_environment={"env": "test"},
            code_version="1.0.0",
            metrics_train={"mae": 0.0010, "rmse": 0.0015, "r2": 0.20},
            metrics_validation={"mae": 0.0012, "rmse": 0.0018, "r2": 0.15},
            metrics_test={"mae": 0.0014, "rmse": 0.0020, "r2": 0.10},
            baseline_metrics_train={"mae": 0.0020, "rmse": 0.0025, "r2": 0.0},
            baseline_metrics_validation={"mae": 0.0022, "rmse": 0.0028, "r2": 0.0},
            baseline_metrics_test={"mae": 0.0025, "rmse": 0.0030, "r2": 0.0},
        )

        reg_manifest = self.registry.register_candidate(manifest)

        if status == STATUS_VALIDATED:
            reg_manifest = self.registry.validate_candidate(model_id=model_id)
        elif status == STATUS_REJECTED:
            reg_manifest = self.registry.reject_model(
                model_id=model_id,
                reason="Synthetic rejection",
            )
        elif status == STATUS_REVOKED:
            self.registry.validate_candidate(model_id=model_id)
            reg_manifest = self.registry.revoke_model(
                model_id=model_id,
                reason="Synthetic revocation",
            )

        return reg_manifest

    # -------------------------------------------------------------------------
    # TESTES DE CONFIGURAÇÃO E BASELINE (OFF)
    # -------------------------------------------------------------------------

    def test_01_adaptive_off_default_matches_paper_baseline(self) -> None:
        """1. ADAPTIVE_MODE='off' por padrão preserva comportamento exato do Paper anterior."""
        prices = [10.0] * 15
        candles = _make_closed_candles(prices)
        now_ms = candles[-1].timestamp + 60000

        result = execute_paper_cycle(
            storage=self.storage,
            config=self.config,
            now_ms=now_ms,
            ticker_override=10.0,
            candles_override=candles,
        )

        self.assertEqual(result.signal, Signal.HOLD)
        self.assertEqual(result.trade_action, "HOLD")
        self.assertIsNotNone(result.adaptive_result)
        self.assertEqual(result.adaptive_result.mode, MODE_OFF)
        self.assertIsNone(result.adaptive_result.record)

        # Garante que nenhuma predição foi persistida na tabela adaptativa
        preds = self.storage.get_adaptive_predictions()
        self.assertEqual(len(preds), 0)

    # -------------------------------------------------------------------------
    # TESTES DE VALIDAÇÃO E GATES DE SEGURANÇA (FAIL-CLOSED)
    # -------------------------------------------------------------------------

    def test_02_real_rejected_model_blocked(self) -> None:
        """2. O modelo real Ridge (model_b3e792893e42fd40) REJECTED é estritamente bloqueado."""
        real_registry_db = Path("data/lab/results/model_registry/model_registry.sqlite3")
        if not real_registry_db.exists():
            self.skipTest("Banco real de Model Registry não encontrado.")

        real_model_id = "model_b3e792893e42fd40"
        model, error = load_validated_model(real_model_id, registry_db=real_registry_db)

        self.assertIsNone(model)
        self.assertEqual(error, "MODEL_REJECTED")

        # Testa execução no ciclo paper com modo Shadow apontando para o modelo real
        config = Config(
            paper_initial_cash=10000.0,
            paper_trade_notional=100.0,
            paper_commission=0.001,
            paper_db_path=str(self.paper_db_path),
            paper_timeframe="1m",
            adaptive_mode=MODE_SHADOW,
            adaptive_model_id=real_model_id,
            adaptive_registry_db=str(real_registry_db),
        )

        prices = [10.0] * 15
        candles = _make_closed_candles(prices)
        now_ms = candles[-1].timestamp + 60000

        result = execute_paper_cycle(
            storage=self.storage,
            config=config,
            now_ms=now_ms,
            ticker_override=10.0,
            candles_override=candles,
        )

        # Estratégia operou normalmente em fallback
        self.assertEqual(result.signal, Signal.HOLD)
        self.assertTrue(result.adaptive_result.is_fallback)
        self.assertEqual(result.adaptive_result.fallback_reason, "MODEL_REJECTED")
        self.assertIsNone(result.adaptive_result.record.prediction)
        self.assertFalse(result.adaptive_result.record.prediction_valid)

    def test_03_no_model_configured_triggers_fallback(self) -> None:
        """3. Sem model_id configurado com modo shadow/adaptive produz fallback limpo."""
        config = Config(
            paper_initial_cash=10000.0,
            paper_trade_notional=100.0,
            paper_commission=0.001,
            paper_db_path=str(self.paper_db_path),
            paper_timeframe="1m",
            adaptive_mode=MODE_SHADOW,
            adaptive_model_id="",
            adaptive_registry_db=str(self.registry_db_path),
        )

        prices = [10.0] * 15
        candles = _make_closed_candles(prices)
        now_ms = candles[-1].timestamp + 60000

        result = execute_paper_cycle(
            storage=self.storage,
            config=config,
            now_ms=now_ms,
            ticker_override=10.0,
            candles_override=candles,
        )

        self.assertTrue(result.adaptive_result.is_fallback)
        self.assertEqual(result.adaptive_result.fallback_reason, "NO_MODEL_CONFIGURED")
        self.assertEqual(result.signal, Signal.HOLD)

    def test_04_candidate_model_blocked(self) -> None:
        """4. Modelo com status CANDIDATE é bloqueado com 'MODEL_NOT_VALIDATED'."""
        candidate = self._create_synthetic_model(status=STATUS_CANDIDATE)
        model, error = load_validated_model(candidate.model_id, registry_db=self.registry_db_path)

        self.assertIsNone(model)
        self.assertEqual(error, "MODEL_NOT_VALIDATED")

    def test_05_revoked_model_blocked(self) -> None:
        """5. Modelo com status REVOKED é bloqueado com 'MODEL_REVOKED'."""
        revoked = self._create_synthetic_model(status=STATUS_REVOKED)
        model, error = load_validated_model(revoked.model_id, registry_db=self.registry_db_path)

        self.assertIsNone(model)
        self.assertEqual(error, "MODEL_REVOKED")

    def test_06_missing_model_blocked(self) -> None:
        """6. Modelo inexistente é bloqueado com 'MODEL_NOT_FOUND'."""
        model, error = load_validated_model("model_unknown_12345", registry_db=self.registry_db_path)

        self.assertIsNone(model)
        self.assertEqual(error, "MODEL_NOT_FOUND")

    def test_07_tampered_target_fingerprint_blocked(self) -> None:
        """7. Modelo com integridade comprometida (target fingerprint adulterado) falha com erro de integridade."""
        import json
        model = self._create_synthetic_model(tag="tamper_test", status=STATUS_VALIDATED)
        with self.registry._get_connection() as conn:
            row = conn.execute("SELECT manifest_json FROM model_registry WHERE model_id = ?", (model.model_id,)).fetchone()
            data = json.loads(row["manifest_json"])
            data["target_fingerprint"] = "tampered_target_fp_123"
            conn.execute("UPDATE model_registry SET manifest_json = ? WHERE model_id = ?", (json.dumps(data), model.model_id))
            conn.commit()

        loaded, error = load_validated_model(model.model_id, registry_db=self.registry_db_path)
        self.assertIsNone(loaded)
        self.assertEqual(error, "MODEL_INTEGRITY_FAILURE_TARGET_FINGERPRINT")

    # -------------------------------------------------------------------------
    # TESTES DE SHADOW MODE
    # -------------------------------------------------------------------------

    def test_08_shadow_mode_executes_prediction_without_affecting_final_signal(self) -> None:
        """8. Shadow Mode: predição é calculada e persistida, mas final_signal é estritamente o sinal da estratégia."""
        # Cria modelo com coeficientes que geram predição positiva (LONG_BIAS)
        validated = self._create_synthetic_model(
            status=STATUS_VALIDATED,
            coefficients={"price": 0.001, "close": 0.001},
            intercept=0.01,
        )

        config = Config(
            paper_initial_cash=10000.0,
            paper_trade_notional=100.0,
            paper_commission=0.001,
            paper_db_path=str(self.paper_db_path),
            paper_timeframe="1m",
            adaptive_mode=MODE_SHADOW,
            adaptive_model_id=validated.model_id,
            adaptive_registry_db=str(self.registry_db_path),
        )

        prices = [10.0] * 15  # Estratégia SMA gerará HOLD
        candles = _make_closed_candles(prices)
        now_ms = candles[-1].timestamp + 60000

        result = execute_paper_cycle(
            storage=self.storage,
            config=config,
            now_ms=now_ms,
            ticker_override=10.0,
            candles_override=candles,
        )

        # No Shadow, mesmo que o modelo recomende LONG_BIAS, a estratégia gerou HOLD e o resultado é HOLD
        self.assertEqual(result.signal, Signal.HOLD)
        self.assertEqual(result.trade_action, "HOLD")
        self.assertIsNotNone(result.adaptive_result)
        self.assertFalse(result.adaptive_result.is_fallback)
        self.assertEqual(result.adaptive_result.adaptive_recommendation, REC_LONG_BIAS)
        self.assertEqual(result.adaptive_result.adaptive_signal, Signal.BUY)
        self.assertEqual(result.adaptive_result.final_signal, Signal.HOLD)

        # Auditoria da predição persistida no banco
        preds = self.storage.get_adaptive_predictions(mode=MODE_SHADOW)
        self.assertEqual(len(preds), 1)
        rec = preds[0]
        self.assertEqual(rec["model_id"], validated.model_id)
        self.assertEqual(rec["mode"], MODE_SHADOW)
        self.assertTrue(rec["prediction_valid"])
        self.assertGreater(rec["prediction"], 0.0)
        self.assertEqual(rec["existing_signal"], "HOLD")
        self.assertEqual(rec["final_signal"], "HOLD")
        self.assertTrue(rec["is_disagreement"])

    def test_09_shadow_mode_agreement_when_strategy_and_model_align(self) -> None:
        """9. Shadow Mode: identifica concordância (is_disagreement=False) quando ambos apontam na mesma direção."""
        # Coeficientes negativos geram predição negativa (NO_LONG_BIAS -> HOLD quando posição é NONE)
        validated = self._create_synthetic_model(
            status=STATUS_VALIDATED,
            coefficients={"price": -0.01, "close": -0.01},
            intercept=-0.1,
        )

        config = Config(
            paper_initial_cash=10000.0,
            paper_trade_notional=100.0,
            paper_commission=0.001,
            paper_db_path=str(self.paper_db_path),
            paper_timeframe="1m",
            adaptive_mode=MODE_SHADOW,
            adaptive_model_id=validated.model_id,
            adaptive_registry_db=str(self.registry_db_path),
        )

        prices = [10.0] * 15  # Estratégia gera HOLD
        candles = _make_closed_candles(prices)
        now_ms = candles[-1].timestamp + 60000

        result = execute_paper_cycle(
            storage=self.storage,
            config=config,
            now_ms=now_ms,
            ticker_override=10.0,
            candles_override=candles,
        )

        self.assertEqual(result.signal, Signal.HOLD)
        self.assertEqual(result.adaptive_result.adaptive_recommendation, REC_NO_LONG_BIAS)
        self.assertEqual(result.adaptive_result.adaptive_signal, Signal.HOLD)
        self.assertFalse(result.adaptive_result.record.is_disagreement)

    # -------------------------------------------------------------------------
    # TESTES DE ADAPTIVE MODE E RISK ENGINE
    # -------------------------------------------------------------------------

    def test_10_adaptive_mode_influences_signal_when_risk_permits(self) -> None:
        """10. Adaptive Mode: recomendação adaptativa orienta o sinal operacional e é executada se o Risk autorizar."""
        validated = self._create_synthetic_model(
            status=STATUS_VALIDATED,
            coefficients={"price": 0.001, "close": 0.001},
            intercept=0.05,  # Predição fortemente positiva -> LONG_BIAS
        )

        config = Config(
            paper_initial_cash=10000.0,
            paper_trade_notional=100.0,
            paper_commission=0.001,
            paper_db_path=str(self.paper_db_path),
            paper_timeframe="1m",
            adaptive_mode=MODE_ADAPTIVE,
            adaptive_model_id=validated.model_id,
            adaptive_registry_db=str(self.registry_db_path),
        )

        # Preços constantes: SMA crossover normalmente geraria HOLD
        prices = [20.0] * 15
        candles = _make_closed_candles(prices)
        now_ms = candles[-1].timestamp + 60000

        result = execute_paper_cycle(
            storage=self.storage,
            config=config,
            now_ms=now_ms,
            ticker_override=20.0,
            candles_override=candles,
        )

        # Em Adaptive Mode, o modelo recomendou BUY, o Risk autorizou e a ordem BUY foi executada
        self.assertEqual(result.signal, Signal.BUY)
        self.assertEqual(result.trade_action, "BUY_EXECUTED")
        self.assertIsNotNone(result.executed_trade)
        self.assertEqual(result.executed_trade.side, "BUY")

        # Confirma persistência com auditoria de risco
        preds = self.storage.get_adaptive_predictions(mode=MODE_ADAPTIVE)
        self.assertEqual(len(preds), 1)
        self.assertEqual(preds[0]["risk_decision"], "ALLOWED")
        self.assertEqual(preds[0]["final_signal"], "BUY")

    def test_11_adaptive_mode_strictly_blocked_by_risk_engine(self) -> None:
        """11. Risk Engine é soberano: bloqueia compra adaptativa se regra de risco (ex: Kill Switch) for acionada."""
        validated = self._create_synthetic_model(
            tag="risk_test",
            status=STATUS_VALIDATED,
            coefficients={"price": 0.001, "close": 0.001},
            intercept=0.05,
        )

        # Ativa o kill switch defensivo no Paper Storage
        self.storage.set_kill_switch(True)

        config = Config(
            paper_initial_cash=10000.0,
            paper_trade_notional=100.0,
            paper_commission=0.001,
            paper_db_path=str(self.paper_db_path),
            paper_timeframe="1m",
            adaptive_mode=MODE_ADAPTIVE,
            adaptive_model_id=validated.model_id,
            adaptive_registry_db=str(self.registry_db_path),
        )

        prices = [20.0] * 15
        candles = _make_closed_candles(prices)
        now_ms = candles[-1].timestamp + 60000

        result = execute_paper_cycle(
            storage=self.storage,
            config=config,
            now_ms=now_ms,
            ticker_override=20.0,
            candles_override=candles,
        )

        # O modelo recomendou BUY, mas o Risk Engine bloqueou categoricamente
        self.assertIsNone(result.executed_trade)
        self.assertEqual(result.trade_action, "BLOCKED_KILL_SWITCH_ACTIVE")
        self.assertEqual(result.risk_decision.code, RiskDecisionCode.KILL_SWITCH_ACTIVE)

        # Auditoria: a decisão adaptativa foi registrada como bloqueada pelo risco
        preds = self.storage.get_adaptive_predictions(mode=MODE_ADAPTIVE)
        self.assertEqual(len(preds), 1)
        self.assertEqual(preds[0]["risk_decision"], "KILL_SWITCH_ACTIVE")
        self.assertIn("kill switch", preds[0]["risk_reason"].lower())

    # -------------------------------------------------------------------------
    # TESTES DE INFERÊNCIA E ROBUSTEZ (FALLBACK)
    # -------------------------------------------------------------------------

    def test_12_prediction_error_triggers_fail_closed_fallback(self) -> None:
        """12. Se o modelo falhar ao calcular inferência (ex: NaN/Inf), ativa fallback seguro para a estratégia."""
        # Coeficiente float('nan') gerará NaN na predição
        validated = self._create_synthetic_model(
            tag="nan_test",
            status=STATUS_VALIDATED,
            coefficients={"price": float("nan"), "close": 0.001},
        )

        config = Config(
            paper_initial_cash=10000.0,
            paper_trade_notional=100.0,
            paper_commission=0.001,
            paper_db_path=str(self.paper_db_path),
            paper_timeframe="1m",
            adaptive_mode=MODE_ADAPTIVE,
            adaptive_model_id=validated.model_id,
            adaptive_registry_db=str(self.registry_db_path),
        )

        prices = [20.0] * 15
        candles = _make_closed_candles(prices)
        now_ms = candles[-1].timestamp + 60000

        result = execute_paper_cycle(
            storage=self.storage,
            config=config,
            now_ms=now_ms,
            ticker_override=20.0,
            candles_override=candles,
        )

        # Não deve lançar exceção não tratada; deve fazer fallback para o sinal existente da estratégia
        self.assertTrue(result.adaptive_result.is_fallback)
        self.assertIn("PREDICTION_ERROR", result.adaptive_result.fallback_reason)
        self.assertEqual(result.signal, Signal.HOLD)
        self.assertEqual(result.trade_action, "HOLD")

    def test_13_security_unauthorized_models_never_reach_broker(self) -> None:
        """13. Prova de segurança: modelos não validados ou ausentes nunca alcançam execução direta."""
        import json
        tampered_model = self._create_synthetic_model(tag="tampered_sec", status=STATUS_VALIDATED)
        with self.registry._get_connection() as conn:
            row = conn.execute("SELECT manifest_json FROM model_registry WHERE model_id = ?", (tampered_model.model_id,)).fetchone()
            data = json.loads(row["manifest_json"])
            data["target_fingerprint"] = "corrupted_target_fp"
            conn.execute("UPDATE model_registry SET manifest_json = ? WHERE model_id = ?", (json.dumps(data), tampered_model.model_id))
            conn.commit()

        unauthorized_scenarios = [
            ("missing", "model_non_existent"),
            ("candidate", self._create_synthetic_model(tag="cand_sec", status=STATUS_CANDIDATE).model_id),
            ("rejected", self._create_synthetic_model(tag="rej_sec", status=STATUS_REJECTED).model_id),
            ("revoked", self._create_synthetic_model(tag="rev_sec", status=STATUS_REVOKED).model_id),
            ("tampered", tampered_model.model_id),
        ]

        for i, (label, model_id) in enumerate(unauthorized_scenarios):
            with self.subTest(scenario=label):
                cfg = Config(
                    paper_initial_cash=10000.0,
                    paper_trade_notional=100.0,
                    paper_commission=0.001,
                    paper_db_path=str(self.paper_db_path),
                    paper_timeframe="1m",
                    adaptive_mode=MODE_ADAPTIVE,
                    adaptive_model_id=model_id,
                    adaptive_registry_db=str(self.registry_db_path),
                )
                start_ts = 1700000000000 + (i + 10) * 3600000
                prices = [20.0] * 15
                candles = _make_closed_candles(prices, start_ts=start_ts)
                now_ms = candles[-1].timestamp + 60000

                res = execute_paper_cycle(
                    storage=self.storage,
                    config=cfg,
                    now_ms=now_ms,
                    ticker_override=20.0,
                    candles_override=candles,
                )

                self.assertIsNotNone(res.adaptive_result)
                self.assertTrue(res.adaptive_result.is_fallback)
                self.assertIsNone(res.adaptive_result.adaptive_recommendation)
                self.assertEqual(res.signal, Signal.HOLD)

    def test_14_adaptive_metrics_accumulation(self) -> None:
        """14. Verificação das métricas agregadas do Shadow Mode no SQLite."""
        validated = self._create_synthetic_model(
            status=STATUS_VALIDATED,
            coefficients={"price": 0.001, "close": 0.001},
            intercept=0.01,
        )

        cfg = Config(
            paper_initial_cash=10000.0,
            paper_trade_notional=100.0,
            paper_commission=0.001,
            paper_db_path=str(self.paper_db_path),
            paper_timeframe="1m",
            adaptive_mode=MODE_SHADOW,
            adaptive_model_id=validated.model_id,
            adaptive_registry_db=str(self.registry_db_path),
        )

        # Executa 3 ciclos consecutivos
        for i in range(3):
            prices = [20.0 + i] * 15
            candles = _make_closed_candles(prices, start_ts=1700000000000 + i * 3600000)
            now_ms = candles[-1].timestamp + 60000
            execute_paper_cycle(
                storage=self.storage,
                config=cfg,
                now_ms=now_ms,
                ticker_override=20.0 + i,
                candles_override=candles,
            )

        metrics = self.storage.get_adaptive_metrics()
        self.assertEqual(metrics["total_predictions"], 3)
        self.assertEqual(metrics["valid_predictions"], 3)
        self.assertEqual(metrics["invalid_predictions"], 0)
        self.assertEqual(metrics["disagreements"], 3)
        self.assertEqual(metrics["agreements"], 0)


if __name__ == "__main__":
    unittest.main()
