"""Suíte de testes para Features e Labels do FinBot (FASE 7.9F).

Cobre os 17 testes metodológicos obrigatórios e validação smoke com dataset real:
1. Feature builder retorna somente campos decision-safe.
2. Nenhum outcome aparece nas features.
3. Feature derivada SMA está matematicamente correta.
4. Future return positivo.
5. Future return negativo.
6. Future return zero.
7. Dados insuficientes retornam NULL / None.
8. Horizontes de N candles calculados corretamente (5, 20, 50, 100).
9. Decision candle não usa candle futuro nas features.
10. Alterar candles futuros NÃO altera features (anti-leakage).
11. Alterar candles futuros altera labels adequadamente.
12. Resultados de features e labels são 100% determinísticos.
13. Timestamp/timezone respeita UTC para hour e day_of_week.
14. Nenhuma feature utiliza outcome_at.
15. Nenhuma feature utiliza realized_pnl.
16. Nenhuma feature utiliza future_return_*.
17. Dataset de features/labels é exportado corretamente para CSV e JSON.
18. Smoke validation com dataset real de 10.000 candles.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from finbot.backtest import load_dataset_snapshot
from finbot.exchange import CandleData
from finbot.experience import (
    DecisionContext,
    ExperienceRecord,
    OutcomeContext,
    build_experience_id,
)
from finbot.features import (
    FeatureSet,
    LabelSet,
    build_experience_features_and_labels,
    build_feature_label_dataset,
    build_labels,
    export_features_labels_csv,
    export_features_labels_json,
    extract_features,
)


class TestFeaturesLabels(unittest.TestCase):
    """Testes unitários e metodológicos da FASE 7.9F (Features + Labels)."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _create_synthetic_candles(
        self,
        count: int = 150,
        base_price: float = 100.0,
        step: float = 1.0,
        start_ts: int = 1700000000000,
        interval_ms: int = 300000,  # 5 minutos
    ) -> list[CandleData]:
        """Gera sequência sintética de candles com valores conhecidos."""
        candles = []
        for i in range(count):
            p = base_price + i * step
            candles.append(
                CandleData(
                    timestamp=start_ts + i * interval_ms,
                    open=p,
                    high=p + 2.0,
                    low=p - 2.0,
                    close=p,
                    volume=10.0 + i,
                )
            )
        return candles

    def _create_sample_experience(
        self,
        candle_timestamp: int = 1700000000000,
        decision_at: str = "2026-09-27T12:00:00+00:00",
        price: float = 100.0,
        execution_price: float | None = None,
        outcome: OutcomeContext | None = None,
    ) -> ExperienceRecord:
        """Cria um ExperienceRecord de teste."""
        dec = DecisionContext(
            decision_at=decision_at,
            candle_timestamp=candle_timestamp,
            symbol="BTC/USDT",
            timeframe="5m",
            price=price,
            open=price,
            high=price + 2.0,
            low=price - 2.0,
            close=price,
            volume=15.0,
            strategy_name="SMA_CROSSOVER",
            strategy_version="1.0.0",
            strategy_parameters={"short_window": 5, "long_window": 10},
            signal="BUY",
            signal_reason="SMA Crossover BUY signal",
            position_before="NONE",
            risk_decision="ALLOWED",
            risk_reason="Risk limits checked",
            risk_allowed=True,
            execution_price=execution_price,
            execution_quantity=0.1,
            execution_fee=0.01,
        )
        return ExperienceRecord(
            experience_id=build_experience_id("test", f"exp_{candle_timestamp}"),
            source="test",
            source_id=f"exp_{candle_timestamp}",
            run_id="run_test",
            decision=dec,
            outcome=outcome,
        )

    # -------------------------------------------------------------------------
    # Teste 1: Feature builder retorna somente campos decision-safe
    # -------------------------------------------------------------------------
    def test_01_feature_builder_decision_safe_fields(self) -> None:
        """Teste 1: Feature builder retorna exclusivamente campos decision-safe."""
        candles = self._create_synthetic_candles(count=20)
        exp = self._create_sample_experience(candle_timestamp=candles[10].timestamp)

        features = extract_features(exp, historical_candles=candles[:11])
        self.assertIsInstance(features, FeatureSet)

        d = features.to_dict()
        expected_keys = {
            "experience_id", "source", "source_id", "run_id", "decision_at",
            "candle_timestamp", "symbol", "timeframe", "price", "open", "high",
            "low", "close", "volume", "short_window", "long_window", "sma_short",
            "sma_long", "sma_distance", "sma_ratio", "signal", "signal_reason",
            "position_before", "risk_decision", "risk_reason", "risk_allowed",
            "hour", "day_of_week",
        }
        self.assertEqual(set(d.keys()), expected_keys)

    # -------------------------------------------------------------------------
    # Teste 2: Nenhum outcome aparece nas features
    # -------------------------------------------------------------------------
    def test_02_no_outcome_in_features(self) -> None:
        """Teste 2: Nenhum campo de desfecho ou label contamina as features."""
        outcome = OutcomeContext(
            outcome_at="2026-09-27T13:00:00+00:00",
            exit_price=120.0,
            realized_pnl=20.0,
            realized_return=0.20,
            fees=0.05,
            future_return_5=0.05,
            future_return_20=0.10,
            outcome="WIN",
        )
        exp = self._create_sample_experience(outcome=outcome)
        features = extract_features(exp)
        f_dict = features.to_dict()

        outcome_fields = [
            "outcome_at", "exit_price", "realized_pnl", "realized_return",
            "fees", "mfe", "mae", "trade_duration", "future_return_5",
            "future_return_20", "future_return_50", "future_return_100", "outcome",
        ]
        for f in outcome_fields:
            self.assertNotIn(f, f_dict, f"Vazamento detectado: campo '{f}' presente nas features!")

    # -------------------------------------------------------------------------
    # Teste 3: Feature derivada SMA está matematicamente correta
    # -------------------------------------------------------------------------
    def test_03_derived_sma_features_math(self) -> None:
        """Teste 3: Verificação matemática exata de sma_distance e sma_ratio."""
        # 10 candles com fechamento constante de 100.0, exceto os últimos 5 com 110.0
        # Closes: [100, 100, 100, 100, 100, 110, 110, 110, 110, 110]
        candles = []
        for i in range(10):
            p = 100.0 if i < 5 else 110.0
            candles.append(CandleData(timestamp=1000 + i * 100, open=p, high=p, low=p, close=p, volume=1.0))

        exp = self._create_sample_experience(candle_timestamp=candles[-1].timestamp)
        features = extract_features(exp, historical_candles=candles)

        # short_window = 5: média dos últimos 5 = 110.0
        self.assertEqual(features.sma_short, 110.0)
        # long_window = 10: média dos 10 = (500 + 550) / 10 = 105.0
        self.assertEqual(features.sma_long, 105.0)
        # sma_distance = 110.0 - 105.0 = 5.0
        self.assertAlmostEqual(features.sma_distance, 5.0, places=5)
        # sma_ratio = 110.0 / 105.0 = 1.047619
        self.assertAlmostEqual(features.sma_ratio, round(110.0 / 105.0, 6), places=5)

    # -------------------------------------------------------------------------
    # Teste 4: Future return positivo
    # -------------------------------------------------------------------------
    def test_04_positive_future_return(self) -> None:
        """Teste 4: Retorno futuro positivo calculado a partir de Open[t+1]."""
        # t=0: Open[t+1] = 100.0, Close[t+5] = 105.0 -> Retorno = (105 - 100) / 100 = +5.0%
        candles = self._create_synthetic_candles(count=20, base_price=100.0, step=1.0)
        # Ajusta especificamente os preços de teste
        # Candle 0 (t): decision candle
        # Candle 1 (t+1): Open = 100.0
        # Candle 5 (t+5): Close = 105.0
        candles[1] = CandleData(timestamp=candles[1].timestamp, open=100.0, high=102.0, low=99.0, close=101.0, volume=1.0)
        candles[5] = CandleData(timestamp=candles[5].timestamp, open=104.0, high=106.0, low=103.0, close=105.0, volume=1.0)

        exp = self._create_sample_experience(candle_timestamp=candles[0].timestamp)
        labels = build_labels(exp, candles=candles, horizons=[5])

        self.assertEqual(labels.reference_price, 100.0)
        self.assertEqual(labels.future_return_5, 0.05)

    # -------------------------------------------------------------------------
    # Teste 5: Future return negativo
    # -------------------------------------------------------------------------
    def test_05_negative_future_return(self) -> None:
        """Teste 5: Retorno futuro negativo calculado a partir de Open[t+1]."""
        # Open[t+1] = 100.0, Close[t+5] = 95.0 -> Retorno = (95 - 100) / 100 = -5.0%
        candles = self._create_synthetic_candles(count=20, base_price=100.0, step=1.0)
        candles[1] = CandleData(timestamp=candles[1].timestamp, open=100.0, high=101.0, low=99.0, close=99.0, volume=1.0)
        candles[5] = CandleData(timestamp=candles[5].timestamp, open=96.0, high=97.0, low=94.0, close=95.0, volume=1.0)

        exp = self._create_sample_experience(candle_timestamp=candles[0].timestamp)
        labels = build_labels(exp, candles=candles, horizons=[5])

        self.assertEqual(labels.reference_price, 100.0)
        self.assertEqual(labels.future_return_5, -0.05)

    # -------------------------------------------------------------------------
    # Teste 6: Future return zero
    # -------------------------------------------------------------------------
    def test_06_zero_future_return(self) -> None:
        """Teste 6: Retorno futuro nulo (0%) quando preço futuro é idêntico à entrada."""
        # Open[t+1] = 100.0, Close[t+5] = 100.0 -> Retorno = 0.0
        candles = self._create_synthetic_candles(count=20, base_price=100.0, step=1.0)
        candles[1] = CandleData(timestamp=candles[1].timestamp, open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0)
        candles[5] = CandleData(timestamp=candles[5].timestamp, open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0)

        exp = self._create_sample_experience(candle_timestamp=candles[0].timestamp)
        labels = build_labels(exp, candles=candles, horizons=[5])

        self.assertEqual(labels.reference_price, 100.0)
        self.assertEqual(labels.future_return_5, 0.0)

    # -------------------------------------------------------------------------
    # Teste 7: Dados insuficientes retornam NULL / None
    # -------------------------------------------------------------------------
    def test_07_insufficient_data_returns_null(self) -> None:
        """Teste 7: Horizontes que ultrapassam o dataset retornam estritamente None (nunca 0)."""
        # Dataset com apenas 10 candles: horizonte 5 existe, mas horizontes 20, 50, 100 não existem
        candles = self._create_synthetic_candles(count=10)
        exp = self._create_sample_experience(candle_timestamp=candles[0].timestamp)

        labels = build_labels(exp, candles=candles, horizons=(5, 20, 50, 100))

        self.assertIsNotNone(labels.future_return_5)
        self.assertIsNone(labels.future_return_20)
        self.assertIsNone(labels.future_return_50)
        self.assertIsNone(labels.future_return_100)

        # Se for no último candle, nem o candle t+1 existe -> todos devem ser None
        last_exp = self._create_sample_experience(candle_timestamp=candles[-1].timestamp)
        last_labels = build_labels(last_exp, candles=candles, horizons=(5, 20, 50, 100))
        self.assertIsNone(last_labels.reference_price)
        self.assertIsNone(last_labels.future_return_5)

    # -------------------------------------------------------------------------
    # Teste 8: Horizontes são calculados corretamente
    # -------------------------------------------------------------------------
    def test_08_horizons_indices_accuracy(self) -> None:
        """Teste 8: Horizontes 5, 20, 50 e 100 utilizam estritamente Close[t+N]."""
        # Preços: Open[i] = i, Close[i] = i
        # t = 10 -> candle 10
        # Open[t+1] = Open[11] = 11.0 (preço de referência)
        # Close[t+5] = Close[15] = 15.0 -> ret = (15 - 11) / 11 = 4 / 11
        # Close[t+20] = Close[30] = 30.0 -> ret = (30 - 11) / 11 = 19 / 11
        # Close[t+50] = Close[60] = 60.0 -> ret = (60 - 11) / 11 = 49 / 11
        # Close[t+100] = Close[110] = 110.0 -> ret = (110 - 11) / 11 = 99 / 11
        candles = [
            CandleData(timestamp=1000 + i * 300, open=float(i), high=float(i + 1), low=float(i - 1), close=float(i), volume=1.0)
            for i in range(120)
        ]
        exp = self._create_sample_experience(candle_timestamp=candles[10].timestamp)
        labels = build_labels(exp, candles=candles, horizons=(5, 20, 50, 100))

        ref = 11.0
        self.assertEqual(labels.reference_price, ref)
        self.assertEqual(labels.future_return_5, round((15.0 - ref) / ref, 8))
        self.assertEqual(labels.future_return_20, round((30.0 - ref) / ref, 8))
        self.assertEqual(labels.future_return_50, round((60.0 - ref) / ref, 8))
        self.assertEqual(labels.future_return_100, round((110.0 - ref) / ref, 8))

    # -------------------------------------------------------------------------
    # Teste 9: Decision candle não usa candle futuro nas features
    # -------------------------------------------------------------------------
    def test_09_decision_candle_temporal_boundary(self) -> None:
        """Teste 9: Candles em t+1, t+2 jamais afetam o cálculo de features em t."""
        candles = self._create_synthetic_candles(count=20, base_price=100.0)
        exp = self._create_sample_experience(candle_timestamp=candles[10].timestamp)

        # Fornece histórico apenas até t=10
        feats_only_past = extract_features(exp, historical_candles=candles[:11])
        # Fornece histórico completo incluindo futuros t=11..19
        feats_with_future = extract_features(exp, historical_candles=candles)

        self.assertEqual(feats_only_past.to_dict(), feats_with_future.to_dict())

    # -------------------------------------------------------------------------
    # Teste 10: Alterar candles futuros não altera features
    # -------------------------------------------------------------------------
    def test_10_leakage_mutating_future_does_not_affect_features(self) -> None:
        """Teste 10 (Anti-leakage): Mutação drástica nos candles futuros tem ZERO efeito nas features."""
        candles_clean = self._create_synthetic_candles(count=30, base_price=100.0)
        # Cria cópia com futuro multiplicado por 10
        candles_mutated = []
        for i, c in enumerate(candles_clean):
            if i > 10:
                candles_mutated.append(
                    CandleData(
                        timestamp=c.timestamp,
                        open=c.open * 10.0,
                        high=c.high * 10.0,
                        low=c.low * 10.0,
                        close=c.close * 10.0,
                        volume=c.volume * 10.0,
                    )
                )
            else:
                candles_mutated.append(c)

        exp = self._create_sample_experience(candle_timestamp=candles_clean[10].timestamp)

        feats_clean = extract_features(exp, historical_candles=candles_clean)
        feats_mutated = extract_features(exp, historical_candles=candles_mutated)

        self.assertEqual(feats_clean.to_dict(), feats_mutated.to_dict())

    # -------------------------------------------------------------------------
    # Teste 11: Alterar candles futuros altera labels adequadamente
    # -------------------------------------------------------------------------
    def test_11_mutating_future_changes_labels(self) -> None:
        """Teste 11: Mutações nos candles futuros alteram os labels de forma esperada."""
        candles_clean = self._create_synthetic_candles(count=30, base_price=100.0)
        # Altera o fechamento do candle futuro em t+5 (índice 15)
        candles_mutated = [
            CandleData(
                timestamp=c.timestamp,
                open=c.open,
                high=c.high,
                low=c.low,
                close=c.close + 50.0 if i == 15 else c.close,
                volume=c.volume,
            )
            for i, c in enumerate(candles_clean)
        ]

        exp = self._create_sample_experience(candle_timestamp=candles_clean[10].timestamp)

        labels_clean = build_labels(exp, candles=candles_clean, horizons=[5])
        labels_mutated = build_labels(exp, candles=candles_mutated, horizons=[5])

        self.assertNotEqual(labels_clean.future_return_5, labels_mutated.future_return_5)

    # -------------------------------------------------------------------------
    # Teste 12: Resultados são determinísticos
    # -------------------------------------------------------------------------
    def test_12_determinism(self) -> None:
        """Teste 12: Execuções repetidas produzem resultados rigorosamente idênticos."""
        candles = self._create_synthetic_candles(count=50)
        exp = self._create_sample_experience(candle_timestamp=candles[15].timestamp)

        f1, l1 = build_experience_features_and_labels(exp, candles=candles)
        f2, l2 = build_experience_features_and_labels(exp, candles=candles)

        self.assertEqual(f1.to_dict(), f2.to_dict())
        self.assertEqual(l1.to_dict(), l2.to_dict())

    # -------------------------------------------------------------------------
    # Teste 13: Timestamp/timezone respeita UTC para hour e day_of_week
    # -------------------------------------------------------------------------
    def test_13_utc_temporal_features(self) -> None:
        """Teste 13: hour e day_of_week são calculados estritamente em UTC a partir de decision_at."""
        # 2026-09-27 foi um Domingo (day_of_week = 6)
        exp_sun = self._create_sample_experience(decision_at="2026-09-27T15:45:00+00:00")
        f_sun = extract_features(exp_sun)
        self.assertEqual(f_sun.hour, 15)
        self.assertEqual(f_sun.day_of_week, 6)

        # 2026-09-28 é uma Segunda-feira (day_of_week = 0)
        exp_mon = self._create_sample_experience(decision_at="2026-09-28T03:10:00+00:00")
        f_mon = extract_features(exp_mon)
        self.assertEqual(f_mon.hour, 3)
        self.assertEqual(f_mon.day_of_week, 0)

    # -------------------------------------------------------------------------
    # Teste 14: Nenhuma feature utiliza outcome_at
    # -------------------------------------------------------------------------
    def test_14_no_feature_uses_outcome_at(self) -> None:
        """Teste 14: Garante que outcome_at jamais é incluído nas features."""
        outcome = OutcomeContext(outcome_at="2026-09-27T16:00:00+00:00", outcome="WIN")
        exp = self._create_sample_experience(outcome=outcome)
        f_dict = extract_features(exp).to_dict()
        self.assertNotIn("outcome_at", f_dict)

    # -------------------------------------------------------------------------
    # Teste 15: Nenhuma feature utiliza realized_pnl
    # -------------------------------------------------------------------------
    def test_15_no_feature_uses_realized_pnl(self) -> None:
        """Teste 15: Garante que realized_pnl jamais é incluído nas features."""
        outcome = OutcomeContext(realized_pnl=55.0, outcome="WIN")
        exp = self._create_sample_experience(outcome=outcome)
        f_dict = extract_features(exp).to_dict()
        self.assertNotIn("realized_pnl", f_dict)

    # -------------------------------------------------------------------------
    # Teste 16: Nenhuma feature utiliza future_return_*
    # -------------------------------------------------------------------------
    def test_16_no_feature_uses_future_return(self) -> None:
        """Teste 16: Garante que future_return_* jamais é incluído nas features."""
        outcome = OutcomeContext(future_return_5=0.012, future_return_20=0.045, outcome="WIN")
        exp = self._create_sample_experience(outcome=outcome)
        f_dict = extract_features(exp).to_dict()
        for k in f_dict:
            self.assertFalse(k.startswith("future_return_"), f"Campo futuro '{k}' encontrado nas features!")

    # -------------------------------------------------------------------------
    # Teste 17: Dataset de features/labels é exportado corretamente
    # -------------------------------------------------------------------------
    def test_17_dataset_export_csv_and_json(self) -> None:
        """Teste 17: Exportação determinística de Feature/Label dataset para CSV e JSON."""
        candles = self._create_synthetic_candles(count=40)
        exps = [
            self._create_sample_experience(candle_timestamp=candles[i].timestamp)
            for i in range(5, 10)
        ]
        dataset = build_feature_label_dataset(exps, candles=candles)
        self.assertEqual(len(dataset), 5)

        export_dir = Path(self.temp_dir.name) / "fl_export"
        csv_file = export_dir / "features_labels.csv"
        json_file = export_dir / "features_labels.json"

        out_csv = export_features_labels_csv(dataset, csv_file)
        out_json = export_features_labels_json(dataset, json_file)

        self.assertTrue(out_csv.exists())
        self.assertTrue(out_json.exists())

        # Valida JSON
        with open(out_json, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)
        self.assertIn("sma_distance", data[0])
        self.assertIn("future_return_5", data[0])

    # -------------------------------------------------------------------------
    # Teste 18: Smoke validation com dataset real de 10.000 candles
    # -------------------------------------------------------------------------
    def test_18_smoke_validation_real_dataset_10k(self) -> None:
        """Teste 18: Smoke test com dataset congelado de 10.000 candles da Binance Spot."""
        dataset_path = Path("data/backtest/binance_BTCUSDT_5m_10000.json")
        if not dataset_path.exists():
            self.skipTest(f"Dataset {dataset_path} não encontrado no repositório.")

        _, candles = load_dataset_snapshot(dataset_path)
        self.assertEqual(len(candles), 10000)

        # Seleciona 3 candles amostrais (início, meio, final próximo ao limite)
        sample_indices = [50, 5000, 9950]
        exps = [
            self._create_sample_experience(
                candle_timestamp=candles[idx].timestamp,
                price=float(candles[idx].close),
            )
            for idx in sample_indices
        ]

        dataset = build_feature_label_dataset(exps, candles=candles)
        self.assertEqual(len(dataset), 3)

        # Amostra do início (idx=50): possui histórico suficiente e futuros suficientes
        row_0 = dataset[0]
        self.assertIsNotNone(row_0["sma_short"])
        self.assertIsNotNone(row_0["sma_long"])
        self.assertIsNotNone(row_0["future_return_5"])
        self.assertIsNotNone(row_0["future_return_20"])
        self.assertIsNotNone(row_0["future_return_50"])

        # Amostra do fim (idx=9950): horizonte de 100 candles excede 10.000 (9950 + 100 = 10050 >= 10000)
        # Deve retornar estritamente None (NULL) para future_return_100
        row_last = dataset[2]
        self.assertIsNotNone(row_last["future_return_5"])
        self.assertIsNotNone(row_last["future_return_20"])
        self.assertIsNone(row_last["future_return_100"])


if __name__ == "__main__":
    unittest.main()
