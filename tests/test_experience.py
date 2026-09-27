"""Testes unitários para o Experience Dataset do FinBot (FASE 7.9E).

Cobre os 12 testes metodológicos obrigatórios:
1. Schema da tabela e integridade do banco SQLite.
2. Criação de experiência válida.
3. Leitura e recuperação de experiência.
4. Deduplicação com chave (source, source_id).
5. Existência inicial sem outcome (Decision Experience).
6. Finalização posterior de outcome.
7. Anti-leakage e isolamento de features em Decision Time.
8. Temporalidade estrita (outcome_at >= decision_at).
9. Provenance (source, source_id, run_id).
10. Exportação determinística para CSV e JSON.
11. Persistência e sobrevivência a restart de conexão.
12. Tratamento estrito de dados ausentes (NULL / None, sem zeros fabricados).
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from finbot.experience import (
    DecisionContext,
    ExperienceRecord,
    ExperienceStorage,
    OutcomeContext,
    build_experience_id,
    create_experience_from_backtest_trade,
    create_experience_from_paper_cycle,
)
from finbot.storage import PaperAccount, PaperPosition, PaperStorage, PaperTrade
from finbot.strategy import Signal


class TestExperienceDataset(unittest.TestCase):
    """Bateria de testes metodológicos da fundação do Experience Dataset."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_experience.sqlite3"
        self.storage = ExperienceStorage(db_path=self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _make_sample_decision(
        self,
        decision_at: str = "2026-09-27T02:00:00+00:00",
        price: float = 65000.0,
        signal: str = "BUY",
        risk_decision: str = "ALLOWED",
        risk_allowed: bool = True,
        open_val: float | None = 64900.0,
        high_val: float | None = 65100.0,
        low_val: float | None = 64850.0,
        close_val: float | None = 65000.0,
        volume_val: float | None = 12.5,
    ) -> DecisionContext:
        return DecisionContext(
            decision_at=decision_at,
            candle_timestamp=1700000000000,
            symbol="BTC/USDT",
            timeframe="5m",
            price=price,
            open=open_val,
            high=high_val,
            low=low_val,
            close=close_val,
            volume=volume_val,
            strategy_name="SMA_CROSSOVER",
            strategy_version="1.0.0",
            strategy_parameters={"short_window": 5, "long_window": 10},
            signal=signal,
            signal_reason="SMA curta cruzou acima da SMA longa",
            position_before="NONE",
            risk_decision=risk_decision,
            risk_reason="Operação autorizada dentro dos limites",
            risk_allowed=risk_allowed,
            execution_price=price if risk_allowed and signal == "BUY" else None,
            execution_quantity=0.0015 if risk_allowed and signal == "BUY" else None,
            execution_fee=0.10 if risk_allowed and signal == "BUY" else None,
        )

    # -------------------------------------------------------------------------
    # Teste 1 — schema
    # -------------------------------------------------------------------------
    def test_01_schema_creation(self) -> None:
        """Teste 1: A tabela experiences e índices são criados corretamente no SQLite."""
        with self.storage.connection() as conn:
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='experiences';"
            )
            self.assertIsNotNone(cur.fetchone())

            # Verifica presença de colunas chave
            col_cur = conn.execute("PRAGMA table_info(experiences);")
            cols = {row["name"]: row["type"] for row in col_cur.fetchall()}
            self.assertIn("experience_id", cols)
            self.assertIn("source", cols)
            self.assertIn("source_id", cols)
            self.assertIn("run_id", cols)
            self.assertIn("decision_at", cols)
            self.assertIn("candle_timestamp", cols)
            self.assertIn("outcome_at", cols)
            self.assertIn("realized_pnl", cols)
            self.assertIn("future_return_20", cols)

            # Verifica índices
            idx_cur = conn.execute("SELECT name FROM sqlite_master WHERE type='index';")
            idx_names = [row["name"] for row in idx_cur.fetchall()]
            self.assertIn("idx_experiences_source", idx_names)
            self.assertIn("idx_experiences_run_id", idx_names)
            self.assertIn("idx_experiences_decision_at", idx_names)

    # -------------------------------------------------------------------------
    # Teste 2 — criação
    # -------------------------------------------------------------------------
    def test_02_creation_valid_experience(self) -> None:
        """Teste 2: É possível criar e salvar uma experiência válida."""
        decision = self._make_sample_decision()
        exp_id = build_experience_id("paper", "trade_001")
        record = ExperienceRecord(
            experience_id=exp_id,
            source="paper",
            source_id="trade_001",
            run_id="run_test",
            decision=decision,
            outcome=None,
        )
        saved = self.storage.save_experience(record)
        self.assertTrue(saved)
        self.assertEqual(self.storage.count(), 1)

    # -------------------------------------------------------------------------
    # Teste 3 — leitura
    # -------------------------------------------------------------------------
    def test_03_reading_retrieval(self) -> None:
        """Teste 3: A experiência salva pode ser recuperada por ID e por source/source_id com integridade."""
        decision = self._make_sample_decision(price=62500.0)
        exp_id = build_experience_id("backtest", "bt_trade_10")
        record = ExperienceRecord(
            experience_id=exp_id,
            source="backtest",
            source_id="bt_trade_10",
            run_id="wfa_window_1",
            decision=decision,
        )
        self.storage.save_experience(record)

        # Recupera por ID
        retrieved_by_id = self.storage.get_experience(exp_id)
        self.assertIsNotNone(retrieved_by_id)
        self.assertEqual(retrieved_by_id.experience_id, exp_id)
        self.assertEqual(retrieved_by_id.source, "backtest")
        self.assertEqual(retrieved_by_id.source_id, "bt_trade_10")
        self.assertEqual(retrieved_by_id.run_id, "wfa_window_1")
        self.assertEqual(retrieved_by_id.decision.price, 62500.0)
        self.assertEqual(retrieved_by_id.decision.symbol, "BTC/USDT")
        self.assertEqual(retrieved_by_id.decision.strategy_parameters, {"short_window": 5, "long_window": 10})

        # Recupera por proveniência
        retrieved_by_source = self.storage.get_by_source("backtest", "bt_trade_10")
        self.assertIsNotNone(retrieved_by_source)
        self.assertEqual(retrieved_by_source.experience_id, exp_id)

    # -------------------------------------------------------------------------
    # Teste 4 — deduplicação
    # -------------------------------------------------------------------------
    def test_04_deduplication(self) -> None:
        """Teste 4: Registrar a mesma experiência duas vezes não cria duplicata."""
        decision = self._make_sample_decision()
        exp_id = build_experience_id("paper", "unique_op_123")
        record1 = ExperienceRecord(
            experience_id=exp_id,
            source="paper",
            source_id="unique_op_123",
            run_id="run_1",
            decision=decision,
        )
        # Primeira inserção: deve suceder
        first_save = self.storage.save_experience(record1)
        self.assertTrue(first_save)
        self.assertEqual(self.storage.count(), 1)

        # Segunda inserção idêntica: deve ser ignorada sem duplicar
        record2 = ExperienceRecord(
            experience_id=exp_id,
            source="paper",
            source_id="unique_op_123",
            run_id="run_1",
            decision=decision,
        )
        second_save = self.storage.save_experience(record2)
        self.assertFalse(second_save)
        self.assertEqual(self.storage.count(), 1)

    # -------------------------------------------------------------------------
    # Teste 5 — decision/outcome
    # -------------------------------------------------------------------------
    def test_05_decision_without_outcome(self) -> None:
        """Teste 5: Uma experiência pode existir inicialmente sem outcome preenchido."""
        decision = self._make_sample_decision()
        record = ExperienceRecord(
            experience_id="exp_pending_outcome",
            source="paper",
            source_id="trade_in_progress",
            run_id="run_soak",
            decision=decision,
            outcome=None,
        )
        self.storage.save_experience(record)

        loaded = self.storage.get_experience("exp_pending_outcome")
        self.assertIsNotNone(loaded)
        self.assertTrue(loaded.is_decision_only())
        self.assertFalse(loaded.is_finalized())
        self.assertIsNone(loaded.outcome.outcome_at)
        self.assertIsNone(loaded.outcome.realized_pnl)
        self.assertIsNone(loaded.outcome.exit_price)
        self.assertIsNone(loaded.outcome.outcome)

    # -------------------------------------------------------------------------
    # Teste 6 — finalização
    # -------------------------------------------------------------------------
    def test_06_outcome_finalization(self) -> None:
        """Teste 6: Posteriormente o outcome pode ser preenchido preservando os dados da decisão."""
        decision = self._make_sample_decision(decision_at="2026-09-27T10:00:00+00:00")
        exp_id = "exp_to_finalize"
        record = ExperienceRecord(
            experience_id=exp_id,
            source="paper",
            source_id="trade_open_close",
            run_id="run_soak",
            decision=decision,
            outcome=None,
        )
        self.storage.save_experience(record)

        # Atualiza outcome após o fechamento da posição
        resolved_outcome = OutcomeContext(
            outcome_at="2026-09-27T10:30:00+00:00",
            exit_price=66000.0,
            realized_pnl=1.50,
            realized_return=0.015,
            fees=0.20,
            trade_duration=1800.0,
            outcome="WIN",
        )
        updated = self.storage.update_outcome(exp_id, resolved_outcome)
        self.assertTrue(updated)

        finalized = self.storage.get_experience(exp_id)
        self.assertIsNotNone(finalized)
        self.assertFalse(finalized.is_decision_only())
        self.assertTrue(finalized.is_finalized())
        self.assertEqual(finalized.outcome.outcome_at, "2026-09-27T10:30:00+00:00")
        self.assertEqual(finalized.outcome.exit_price, 66000.0)
        self.assertEqual(finalized.outcome.realized_pnl, 1.50)
        self.assertEqual(finalized.outcome.outcome, "WIN")
        # Dados de decisão permanecem intactos
        self.assertEqual(finalized.decision.price, 65000.0)
        self.assertEqual(finalized.decision.decision_at, "2026-09-27T10:00:00+00:00")

    # -------------------------------------------------------------------------
    # Teste 7 — anti-leakage
    # -------------------------------------------------------------------------
    def test_07_anti_leakage(self) -> None:
        """Teste 7: Campos futuros não aparecem como dados de decisão em to_feature_dict()."""
        decision = self._make_sample_decision(decision_at="2026-09-27T12:00:00+00:00")
        outcome = OutcomeContext(
            outcome_at="2026-09-27T13:00:00+00:00",
            exit_price=68000.0,
            realized_pnl=30.0,
            realized_return=0.03,
            fees=0.25,
            future_return_5=0.005,
            future_return_20=0.012,
            outcome="WIN",
        )
        record = ExperienceRecord(
            experience_id="exp_leakage_check",
            source="paper",
            source_id="leakage_1",
            run_id="run_leakage",
            decision=decision,
            outcome=outcome,
        )

        features = record.to_feature_dict()

        # Garante que nenhum campo de outcome contamina o dicionário de features
        forbidden_outcome_keys = [
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
        ]
        for key in forbidden_outcome_keys:
            self.assertNotIn(key, features, f"Campo de outcome '{key}' vazou em to_feature_dict()!")

        # Garante que dados de decisão essenciais estão presentes
        self.assertIn("decision_at", features)
        self.assertIn("price", features)
        self.assertIn("strategy_parameters", features)
        self.assertIn("signal", features)
        self.assertIn("risk_decision", features)

    # -------------------------------------------------------------------------
    # Teste 8 — temporalidade
    # -------------------------------------------------------------------------
    def test_08_temporality_validation(self) -> None:
        """Teste 8: Garantir outcome_at >= decision_at e rejeitar violação temporal."""
        decision = self._make_sample_decision(decision_at="2026-09-27T14:00:00+00:00")

        # Caso válido: outcome posterior
        valid_outcome = OutcomeContext(outcome_at="2026-09-27T14:30:00+00:00", outcome="WIN")
        rec_valid = ExperienceRecord(
            experience_id="exp_temp_valid",
            source="paper",
            source_id="temp_1",
            run_id="run_temp",
            decision=decision,
            outcome=valid_outcome,
        )
        self.assertIsNotNone(rec_valid)

        # Caso válido: outcome no mesmo instante (ex: decisão de bloqueio ou hold)
        instant_outcome = OutcomeContext(outcome_at="2026-09-27T14:00:00+00:00", outcome="HOLD")
        rec_instant = ExperienceRecord(
            experience_id="exp_temp_instant",
            source="paper",
            source_id="temp_2",
            run_id="run_temp",
            decision=decision,
            outcome=instant_outcome,
        )
        self.assertIsNotNone(rec_instant)

        # Caso inválido: outcome anterior a decision_at (look-ahead / violação temporal)
        invalid_outcome = OutcomeContext(outcome_at="2026-09-27T13:59:00+00:00", outcome="LOSS")
        with self.assertRaises(ValueError) as ctx:
            ExperienceRecord(
                experience_id="exp_temp_invalid",
                source="paper",
                source_id="temp_3",
                run_id="run_temp",
                decision=decision,
                outcome=invalid_outcome,
            )
        self.assertIn("Violação temporal", str(ctx.exception))

        # Rejeição em update_outcome
        self.storage.save_experience(
            ExperienceRecord(
                experience_id="exp_for_temp_update",
                source="paper",
                source_id="temp_update",
                run_id="run_temp",
                decision=decision,
            )
        )
        with self.assertRaises(ValueError):
            self.storage.update_outcome("exp_for_temp_update", invalid_outcome)

    # -------------------------------------------------------------------------
    # Teste 9 — provenance
    # -------------------------------------------------------------------------
    def test_09_provenance_preservation(self) -> None:
        """Teste 9: A origem da experiência (source, source_id, run_id) é preservada fielmente."""
        sources = [
            ("paper", "cycle_1001", "paper_soak_72h"),
            ("backtest", "trade_42", "full_grid_sma"),
            ("wfa", "cand_3_w2", "wfa_run_20260927"),
            ("research", "spike_vbt_1", "benchmark_fase_79a"),
        ]

        for src, sid, rid in sources:
            rec = ExperienceRecord(
                experience_id=build_experience_id(src, sid),
                source=src,
                source_id=sid,
                run_id=rid,
                decision=self._make_sample_decision(),
            )
            self.storage.save_experience(rec)

        for src, sid, rid in sources:
            loaded = self.storage.get_by_source(src, sid)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.source, src)
            self.assertEqual(loaded.source_id, sid)
            self.assertEqual(loaded.run_id, rid)

        # Filtro de listagem por source
        wfa_list = self.storage.list_experiences(source="wfa")
        self.assertEqual(len(wfa_list), 1)
        self.assertEqual(wfa_list[0].source_id, "cand_3_w2")

    # -------------------------------------------------------------------------
    # Teste 10 — exportação
    # -------------------------------------------------------------------------
    def test_10_deterministic_export(self) -> None:
        """Teste 10: Exportação para CSV e JSON é determinística, ordenada e sem duplicações."""
        export_dir = Path(self.temp_dir.name) / "export_test"

        # Popula 3 experiências com horários sequenciais
        timestamps = [
            "2026-09-27T08:00:00+00:00",
            "2026-09-27T08:05:00+00:00",
            "2026-09-27T08:10:00+00:00",
        ]
        for i, ts in enumerate(timestamps):
            rec = ExperienceRecord(
                experience_id=f"exp_ord_{i}",
                source="paper",
                source_id=f"source_ord_{i}",
                run_id="run_export",
                decision=self._make_sample_decision(decision_at=ts, price=60000.0 + i * 100),
                outcome=OutcomeContext(
                    outcome_at=f"2026-09-27T08:30:0{i}+00:00",
                    exit_price=60050.0 + i * 100,
                    realized_pnl=50.0,
                    outcome="WIN",
                ),
            )
            self.storage.save_experience(rec)

        csv_path = export_dir / "experiences.csv"
        json_path = export_dir / "experiences.json"

        # Executa exportações
        out_csv = self.storage.export_to_csv(csv_path)
        out_json = self.storage.export_to_json(json_path)

        self.assertTrue(out_csv.exists())
        self.assertTrue(out_json.exists())

        # Valida JSON: determinismo e ordenação
        with open(out_json, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)
        self.assertEqual([d["experience_id"] for d in data], ["exp_ord_0", "exp_ord_1", "exp_ord_2"])
        self.assertEqual([d["decision_at"] for d in data], timestamps)

        # Valida CSV: existência de linhas e cabeçalho estável
        with open(out_csv, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
        self.assertEqual(len(lines), 4)  # 1 header + 3 rows
        header = lines[0].split(",")
        self.assertIn("experience_id", header)
        self.assertIn("decision_at", header)
        self.assertIn("realized_pnl", header)

    # -------------------------------------------------------------------------
    # Teste 11 — restart/persistence
    # -------------------------------------------------------------------------
    def test_11_restart_persistence(self) -> None:
        """Teste 11: Experiências sobrevivem ao fechamento e reabertura do banco SQLite."""
        rec = ExperienceRecord(
            experience_id="exp_persisted_1",
            source="paper",
            source_id="persisted_id_1",
            run_id="run_persist",
            decision=self._make_sample_decision(price=64000.0),
            outcome=OutcomeContext(outcome_at="2026-09-27T03:00:00+00:00", realized_pnl=10.0, outcome="WIN"),
        )
        self.storage.save_experience(rec)
        self.assertEqual(self.storage.count(), 1)

        # Simula restart: instancia nova conexão no mesmo arquivo
        new_storage = ExperienceStorage(db_path=self.db_path)
        self.assertEqual(new_storage.count(), 1)
        loaded = new_storage.get_experience("exp_persisted_1")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.decision.price, 64000.0)
        self.assertEqual(loaded.outcome.realized_pnl, 10.0)
        self.assertEqual(loaded.outcome.outcome, "WIN")

    # -------------------------------------------------------------------------
    # Teste 12 — dados ausentes
    # -------------------------------------------------------------------------
    def test_12_missing_data_remains_null(self) -> None:
        """Teste 12: Campos desconhecidos permanecem NULL / None, sem valores artificiais (ex: 0)."""
        # Cria decisão sem OHLCV completo e sem execução
        decision = DecisionContext(
            decision_at="2026-09-27T05:00:00+00:00",
            candle_timestamp=1700000000000,
            symbol="BTC/USDT",
            timeframe="5m",
            price=60000.0,
            strategy_name="SMA_CROSSOVER",
            strategy_version="1.0.0",
            strategy_parameters={"short_window": 5, "long_window": 10},
            signal="HOLD",
            signal_reason="Sem cruzamento",
            position_before="NONE",
            risk_decision="HOLD",
            risk_reason="HOLD",
            risk_allowed=True,
            open=None,
            high=None,
            low=None,
            close=None,
            volume=None,
            execution_price=None,
            execution_quantity=None,
            execution_fee=None,
        )
        # Outcome com labels futuros desconhecidos
        outcome = OutcomeContext(
            outcome_at="2026-09-27T05:00:00+00:00",
            exit_price=None,
            realized_pnl=None,
            realized_return=None,
            fees=None,
            mfe=None,
            mae=None,
            trade_duration=None,
            future_return_5=None,
            future_return_20=None,
            future_return_50=None,
            future_return_100=None,
            outcome="HOLD",
        )
        rec = ExperienceRecord(
            experience_id="exp_null_safety",
            source="paper",
            source_id="hold_null_check",
            run_id="run_null",
            decision=decision,
            outcome=outcome,
        )
        self.storage.save_experience(rec)

        loaded = self.storage.get_experience("exp_null_safety")
        self.assertIsNotNone(loaded)

        # Verifica que campos não preenchidos NÃO foram convertidos para 0
        self.assertIsNone(loaded.decision.open)
        self.assertIsNone(loaded.decision.high)
        self.assertIsNone(loaded.decision.low)
        self.assertIsNone(loaded.decision.volume)
        self.assertIsNone(loaded.decision.execution_price)
        self.assertIsNone(loaded.outcome.realized_pnl)
        self.assertIsNone(loaded.outcome.mfe)
        self.assertIsNone(loaded.outcome.mae)
        self.assertIsNone(loaded.outcome.future_return_5)
        self.assertIsNone(loaded.outcome.future_return_20)
        self.assertIsNone(loaded.outcome.future_return_50)
        self.assertIsNone(loaded.outcome.future_return_100)

    # -------------------------------------------------------------------------
    # Teste complementar: Decision Experience vs Trade Experience
    # -------------------------------------------------------------------------
    def test_decision_vs_trade_experience(self) -> None:
        """Distingue Decision Experience (ex: sinal bloqueado por risco) de Trade Experience."""
        # 1. Decision Experience: sinal de BUY bloqueado por limite diário de risco
        blocked_decision = self._make_sample_decision(
            signal="BUY",
            risk_decision="DAILY_LOSS_LIMIT",
            risk_allowed=False,
        )
        blocked_exp = ExperienceRecord(
            experience_id="exp_blocked_1",
            source="paper",
            source_id="blocked_risk_decision",
            run_id="run_risk_test",
            decision=blocked_decision,
            outcome=OutcomeContext(outcome_at="2026-09-27T02:00:00+00:00", outcome="BLOCKED"),
        )
        self.storage.save_experience(blocked_exp)

        loaded_blocked = self.storage.get_experience("exp_blocked_1")
        self.assertIsNotNone(loaded_blocked)
        self.assertFalse(loaded_blocked.decision.risk_allowed)
        self.assertEqual(loaded_blocked.decision.risk_decision, "DAILY_LOSS_LIMIT")
        self.assertEqual(loaded_blocked.outcome.outcome, "BLOCKED")
        self.assertIsNone(loaded_blocked.decision.execution_price)

        # 2. Trade Experience a partir de um trade fechado de backtest
        mock_bt_trade = {
            "EntryPrice": 61000.0,
            "ExitPrice": 62500.0,
            "PnL": 150.0,
            "ReturnPct": 0.0245,
            "Size": 0.1,
            "EntryTime": "2026-09-27T03:00:00+00:00",
            "ExitTime": "2026-09-27T04:30:00+00:00",
        }
        trade_exp = create_experience_from_backtest_trade(
            trade=mock_bt_trade,
            symbol="BTC/USDT",
            timeframe="5m",
            short_window=5,
            long_window=10,
            run_id="backtest_validation",
            source_id="bt_trade_101",
        )
        self.storage.save_experience(trade_exp)

        loaded_trade = self.storage.get_by_source("backtest", "bt_trade_101")
        self.assertIsNotNone(loaded_trade)
        self.assertTrue(loaded_trade.decision.risk_allowed)
        self.assertEqual(loaded_trade.decision.execution_price, 61000.0)
        self.assertEqual(loaded_trade.outcome.exit_price, 62500.0)
        self.assertEqual(loaded_trade.outcome.realized_pnl, 150.0)
        self.assertEqual(loaded_trade.outcome.outcome, "WIN")


if __name__ == "__main__":
    unittest.main()
