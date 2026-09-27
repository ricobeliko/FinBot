"""Módulo de fundação do Experience Dataset do FinBot (FASE 7.9E).

Implementa o modelo canônico de experiência, separação estrita entre Decision Time
e Outcome Time, garantias anti-leakage, persistência SQLite local, deduplicação
e exportação determinística para pesquisa.
"""

from __future__ import annotations

from contextlib import contextmanager
import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Generator
import uuid


def _parse_iso_utc(ts: str) -> datetime:
    """Converte string ISO8601 para datetime UTC timezone-aware."""
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@dataclass(frozen=True)
class DecisionContext:
    """Informações estritamente disponíveis no instante da decisão (Decision Time).

    FEATURE-SAFE: Estes dados podem futuramente ser utilizados como features.
    Sob NENHUMA circunstância deve conter dados ou métricas posteriores à decisão.
    """

    decision_at: str  # ISO8601 UTC
    candle_timestamp: int  # Timestamp do candle fechado de referência em ms
    symbol: str  # Ex: "BTC/USDT"
    timeframe: str  # Ex: "5m", "1m"
    price: float  # Preço observado de mercado no momento
    strategy_name: str  # Ex: "SMA_CROSSOVER"
    strategy_version: str  # Ex: "1.0.0"
    strategy_parameters: dict[str, Any]  # Ex: {"short_window": 5, "long_window": 10}
    signal: str  # "BUY", "SELL", "HOLD"
    signal_reason: str
    position_before: str  # "NONE", "LONG"
    risk_decision: str  # Ex: "ALLOWED", "BLOCKED_MAX_POSITION", "KILL_SWITCH_ACTIVE"
    risk_reason: str
    risk_allowed: bool
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: float | None = None
    execution_price: float | None = None
    execution_quantity: float | None = None
    execution_fee: float | None = None

    def __post_init__(self) -> None:
        if not self.decision_at:
            raise ValueError("decision_at é obrigatório no DecisionContext.")
        if not self.symbol:
            raise ValueError("symbol é obrigatório no DecisionContext.")
        if self.candle_timestamp < 0:
            raise ValueError(f"candle_timestamp inválido: {self.candle_timestamp}")
        if self.price <= 0:
            raise ValueError(f"price deve ser positivo: {self.price}")


@dataclass(frozen=True)
class OutcomeContext:
    """Informações descobertas exclusivamente APÓS o instante da decisão (Outcome Time).

    OUTCOME-ONLY: Estes dados podem futuramente ser utilizados como labels / targets.
    JAMAIS devem contaminar o snapshot de decisão (anti-leakage).
    Campos desconhecidos devem permanecer None (NULL), nunca valores fictícios como 0.
    """

    outcome_at: str | None = None  # ISO8601 UTC do momento do encerramento/avaliação
    exit_price: float | None = None
    realized_pnl: float | None = None
    realized_return: float | None = None
    fees: float | None = None
    mfe: float | None = None  # Maximum Favorable Excursion
    mae: float | None = None  # Maximum Adverse Excursion
    trade_duration: float | None = None  # Duração em segundos
    future_return_5: float | None = None  # Reservado para Fase 7.9F (NULL se desconhecido)
    future_return_20: float | None = None
    future_return_50: float | None = None
    future_return_100: float | None = None
    outcome: str | None = None  # Ex: "WIN", "LOSS", "BREAK_EVEN", "BLOCKED", "HOLD", "OPEN"


@dataclass(frozen=True)
class ExperienceRecord:
    """Registro canônico e imutável de uma experiência no FinBot."""

    experience_id: str
    source: str  # "paper", "backtest", "wfa", "research"
    source_id: str  # ID único no contexto da fonte (ex: "trade_1", "cycle_1700000000")
    run_id: str  # ID da rodada, sessão ou sweep
    decision: DecisionContext
    outcome: OutcomeContext | None = None
    created_at: str = ""  # ISO8601 UTC

    def __post_init__(self) -> None:
        if not self.experience_id:
            raise ValueError("experience_id não pode ser vazio.")
        if not self.source:
            raise ValueError("source não pode ser vazio.")
        if not self.source_id:
            raise ValueError("source_id não pode ser vazio.")
        if not self.run_id:
            raise ValueError("run_id não pode ser vazio.")

        # Garantia de timestamp de criação
        if not self.created_at:
            object.__setattr__(self, "created_at", datetime.now(timezone.utc).isoformat())

        # Validação temporal estrita (anti-leakage)
        if self.outcome is not None and self.outcome.outcome_at is not None:
            dec_dt = _parse_iso_utc(self.decision.decision_at)
            out_dt = _parse_iso_utc(self.outcome.outcome_at)
            if out_dt < dec_dt:
                raise ValueError(
                    f"Violação temporal anti-leakage: outcome_at ({self.outcome.outcome_at}) "
                    f"não pode anteceder decision_at ({self.decision.decision_at})."
                )

    def is_decision_only(self) -> bool:
        """Indica se a experiência contém apenas dados de decisão sem outcome preenchido."""
        if self.outcome is None:
            return True
        return self.outcome.outcome_at is None and self.outcome.realized_pnl is None

    def is_finalized(self) -> bool:
        """Indica se a experiência possui desfecho (outcome) preenchido."""
        return not self.is_decision_only()

    def with_outcome(self, new_outcome: OutcomeContext) -> ExperienceRecord:
        """Retorna uma nova instância de ExperienceRecord com outcome atualizado."""
        return ExperienceRecord(
            experience_id=self.experience_id,
            source=self.source,
            source_id=self.source_id,
            run_id=self.run_id,
            decision=self.decision,
            outcome=new_outcome,
            created_at=self.created_at,
        )

    def to_feature_dict(self) -> dict[str, Any]:
        """Retorna exclusivamente campos seguros de Decision Time (FEATURE-SAFE).

        Blindagem anti-leakage: campos de outcome (PnL, retornos, etc.) são omitidos.
        """
        return {
            "experience_id": self.experience_id,
            "source": self.source,
            "source_id": self.source_id,
            "run_id": self.run_id,
            "decision_at": self.decision.decision_at,
            "candle_timestamp": self.decision.candle_timestamp,
            "symbol": self.decision.symbol,
            "timeframe": self.decision.timeframe,
            "price": self.decision.price,
            "open": self.decision.open,
            "high": self.decision.high,
            "low": self.decision.low,
            "close": self.decision.close,
            "volume": self.decision.volume,
            "strategy_name": self.decision.strategy_name,
            "strategy_version": self.decision.strategy_version,
            "strategy_parameters": dict(self.decision.strategy_parameters),
            "signal": self.decision.signal,
            "signal_reason": self.decision.signal_reason,
            "position_before": self.decision.position_before,
            "risk_decision": self.decision.risk_decision,
            "risk_reason": self.decision.risk_reason,
            "risk_allowed": self.decision.risk_allowed,
            "execution_price": self.decision.execution_price,
            "execution_quantity": self.decision.execution_quantity,
            "execution_fee": self.decision.execution_fee,
            "created_at": self.created_at,
        }

    def to_outcome_dict(self) -> dict[str, Any]:
        """Retorna exclusivamente campos de Outcome Time (OUTCOME-ONLY)."""
        if self.outcome is None:
            return {
                "experience_id": self.experience_id,
                "outcome_at": None,
                "exit_price": None,
                "realized_pnl": None,
                "realized_return": None,
                "fees": None,
                "mfe": None,
                "mae": None,
                "trade_duration": None,
                "future_return_5": None,
                "future_return_20": None,
                "future_return_50": None,
                "future_return_100": None,
                "outcome": None,
            }
        return {
            "experience_id": self.experience_id,
            "outcome_at": self.outcome.outcome_at,
            "exit_price": self.outcome.exit_price,
            "realized_pnl": self.outcome.realized_pnl,
            "realized_return": self.outcome.realized_return,
            "fees": self.outcome.fees,
            "mfe": self.outcome.mfe,
            "mae": self.outcome.mae,
            "trade_duration": self.outcome.trade_duration,
            "future_return_5": self.outcome.future_return_5,
            "future_return_20": self.outcome.future_return_20,
            "future_return_50": self.outcome.future_return_50,
            "future_return_100": self.outcome.future_return_100,
            "outcome": self.outcome.outcome,
        }

    def to_dict(self) -> dict[str, Any]:
        """Serializa o registro completo em dicionário plano."""
        feat = self.to_feature_dict()
        out = self.to_outcome_dict()
        feat.update(out)
        return feat


class ExperienceStorage:
    """Gerenciador de persistência SQLite para o Experience Dataset.

    Reutiliza a infraestrutura de SQLite local com transações ACID,
    deduplicação via constraint UNIQUE(source, source_id),
    operações idempotentes e exportação determinística para CSV/JSON.
    """

    def __init__(self, db_path: str | Path = "data/finbot_paper.sqlite3", timeout: float = 30.0) -> None:
        self.db_path = Path(db_path)
        self.timeout = timeout
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        """Abre conexão SQLite garantindo diretórios e row_factory."""
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=self.timeout)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Gerencia conexão com commit automático e fechamento seguro."""
        conn = self.get_connection()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def init_db(self) -> None:
        """Cria a tabela de experiências de forma idempotente sem alterar dados existentes."""
        with self.connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS experiences (
                    experience_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    decision_at TEXT NOT NULL,
                    candle_timestamp INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    price REAL NOT NULL,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL,
                    strategy_name TEXT NOT NULL,
                    strategy_version TEXT NOT NULL,
                    strategy_parameters TEXT NOT NULL,
                    signal TEXT NOT NULL,
                    signal_reason TEXT NOT NULL,
                    position_before TEXT NOT NULL,
                    risk_decision TEXT NOT NULL,
                    risk_reason TEXT NOT NULL,
                    risk_allowed INTEGER NOT NULL,
                    execution_price REAL,
                    execution_quantity REAL,
                    execution_fee REAL,
                    outcome_at TEXT,
                    exit_price REAL,
                    realized_pnl REAL,
                    realized_return REAL,
                    fees REAL,
                    mfe REAL,
                    mae REAL,
                    trade_duration REAL,
                    future_return_5 REAL,
                    future_return_20 REAL,
                    future_return_50 REAL,
                    future_return_100 REAL,
                    outcome TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(source, source_id)
                );
            """)

            conn.execute("CREATE INDEX IF NOT EXISTS idx_experiences_source ON experiences(source);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_experiences_run_id ON experiences(run_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_experiences_decision_at ON experiences(decision_at);")

    def save_experience(self, record: ExperienceRecord) -> bool:
        """Salva uma nova experiência. Se (source, source_id) já existir, não duplica.

        Retorna True se inserido, False se já existia.
        Se já existia e o registro atual traz um outcome para completar um record sem outcome,
        chama update_outcome atomicamente.
        """
        params_json = json.dumps(record.decision.strategy_parameters, sort_keys=True)
        out = record.outcome

        with self.connection() as conn:
            cur = conn.execute(
                "SELECT experience_id, outcome_at, realized_pnl FROM experiences WHERE source = ? AND source_id = ?;",
                (record.source, record.source_id),
            )
            existing = cur.fetchone()

            if existing is not None:
                if out is not None and out.outcome_at is not None and existing["outcome_at"] is None:
                    self._update_outcome_in_conn(conn, existing["experience_id"], out)
                return False

            conn.execute(
                """
                INSERT INTO experiences (
                    experience_id, source, source_id, run_id,
                    decision_at, candle_timestamp, symbol, timeframe, price,
                    open, high, low, close, volume,
                    strategy_name, strategy_version, strategy_parameters,
                    signal, signal_reason, position_before,
                    risk_decision, risk_reason, risk_allowed,
                    execution_price, execution_quantity, execution_fee,
                    outcome_at, exit_price, realized_pnl, realized_return, fees,
                    mfe, mae, trade_duration,
                    future_return_5, future_return_20, future_return_50, future_return_100,
                    outcome, created_at
                ) VALUES (
                    ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?
                );
                """,
                (
                    record.experience_id,
                    record.source,
                    record.source_id,
                    record.run_id,
                    record.decision.decision_at,
                    record.decision.candle_timestamp,
                    record.decision.symbol,
                    record.decision.timeframe,
                    record.decision.price,
                    record.decision.open,
                    record.decision.high,
                    record.decision.low,
                    record.decision.close,
                    record.decision.volume,
                    record.decision.strategy_name,
                    record.decision.strategy_version,
                    params_json,
                    record.decision.signal,
                    record.decision.signal_reason,
                    record.decision.position_before,
                    record.decision.risk_decision,
                    record.decision.risk_reason,
                    1 if record.decision.risk_allowed else 0,
                    record.decision.execution_price,
                    record.decision.execution_quantity,
                    record.decision.execution_fee,
                    out.outcome_at if out else None,
                    out.exit_price if out else None,
                    out.realized_pnl if out else None,
                    out.realized_return if out else None,
                    out.fees if out else None,
                    out.mfe if out else None,
                    out.mae if out else None,
                    out.trade_duration if out else None,
                    out.future_return_5 if out else None,
                    out.future_return_20 if out else None,
                    out.future_return_50 if out else None,
                    out.future_return_100 if out else None,
                    out.outcome if out else None,
                    record.created_at,
                ),
            )
            return True

    def _update_outcome_in_conn(
        self,
        conn: sqlite3.Connection,
        experience_id: str,
        outcome: OutcomeContext,
    ) -> bool:
        """Executa update interno dos campos de outcome dentro de uma transação aberta."""
        cur = conn.execute(
            """
            UPDATE experiences SET
                outcome_at = ?,
                exit_price = ?,
                realized_pnl = ?,
                realized_return = ?,
                fees = ?,
                mfe = ?,
                mae = ?,
                trade_duration = ?,
                future_return_5 = ?,
                future_return_20 = ?,
                future_return_50 = ?,
                future_return_100 = ?,
                outcome = ?
            WHERE experience_id = ?;
            """,
            (
                outcome.outcome_at,
                outcome.exit_price,
                outcome.realized_pnl,
                outcome.realized_return,
                outcome.fees,
                outcome.mfe,
                outcome.mae,
                outcome.trade_duration,
                outcome.future_return_5,
                outcome.future_return_20,
                outcome.future_return_50,
                outcome.future_return_100,
                outcome.outcome,
                experience_id,
            ),
        )
        return cur.rowcount > 0

    def update_outcome(self, experience_id: str, outcome: OutcomeContext) -> bool:
        """Atualiza posteriormente os campos de outcome de uma experiência existente.

        Garante validação temporal prévia contra o decision_at registrado.
        """
        with self.connection() as conn:
            cur = conn.execute(
                "SELECT decision_at FROM experiences WHERE experience_id = ?;",
                (experience_id,),
            )
            row = cur.fetchone()
            if not row:
                return False

            if outcome.outcome_at is not None:
                dec_dt = _parse_iso_utc(row["decision_at"])
                out_dt = _parse_iso_utc(outcome.outcome_at)
                if out_dt < dec_dt:
                    raise ValueError(
                        f"Violação temporal anti-leakage: outcome_at ({outcome.outcome_at}) "
                        f"não pode anteceder decision_at ({row['decision_at']})."
                    )

            return self._update_outcome_in_conn(conn, experience_id, outcome)

    def _row_to_record(self, r: sqlite3.Row) -> ExperienceRecord:
        """Converte uma linha de banco de dados em um ExperienceRecord tipado."""
        params = json.loads(r["strategy_parameters"]) if r["strategy_parameters"] else {}

        decision = DecisionContext(
            decision_at=r["decision_at"],
            candle_timestamp=int(r["candle_timestamp"]),
            symbol=r["symbol"],
            timeframe=r["timeframe"],
            price=float(r["price"]),
            open=float(r["open"]) if r["open"] is not None else None,
            high=float(r["high"]) if r["high"] is not None else None,
            low=float(r["low"]) if r["low"] is not None else None,
            close=float(r["close"]) if r["close"] is not None else None,
            volume=float(r["volume"]) if r["volume"] is not None else None,
            strategy_name=r["strategy_name"],
            strategy_version=r["strategy_version"],
            strategy_parameters=params,
            signal=r["signal"],
            signal_reason=r["signal_reason"],
            position_before=r["position_before"],
            risk_decision=r["risk_decision"],
            risk_reason=r["risk_reason"],
            risk_allowed=bool(r["risk_allowed"]),
            execution_price=float(r["execution_price"]) if r["execution_price"] is not None else None,
            execution_quantity=float(r["execution_quantity"]) if r["execution_quantity"] is not None else None,
            execution_fee=float(r["execution_fee"]) if r["execution_fee"] is not None else None,
        )

        outcome = OutcomeContext(
            outcome_at=r["outcome_at"] if r["outcome_at"] is not None else None,
            exit_price=float(r["exit_price"]) if r["exit_price"] is not None else None,
            realized_pnl=float(r["realized_pnl"]) if r["realized_pnl"] is not None else None,
            realized_return=float(r["realized_return"]) if r["realized_return"] is not None else None,
            fees=float(r["fees"]) if r["fees"] is not None else None,
            mfe=float(r["mfe"]) if r["mfe"] is not None else None,
            mae=float(r["mae"]) if r["mae"] is not None else None,
            trade_duration=float(r["trade_duration"]) if r["trade_duration"] is not None else None,
            future_return_5=float(r["future_return_5"]) if r["future_return_5"] is not None else None,
            future_return_20=float(r["future_return_20"]) if r["future_return_20"] is not None else None,
            future_return_50=float(r["future_return_50"]) if r["future_return_50"] is not None else None,
            future_return_100=float(r["future_return_100"]) if r["future_return_100"] is not None else None,
            outcome=r["outcome"] if r["outcome"] is not None else None,
        )

        return ExperienceRecord(
            experience_id=r["experience_id"],
            source=r["source"],
            source_id=r["source_id"],
            run_id=r["run_id"],
            decision=decision,
            outcome=outcome,
            created_at=r["created_at"],
        )

    def get_experience(self, experience_id: str) -> ExperienceRecord | None:
        """Recupera uma experiência pelo seu experience_id."""
        with self.connection() as conn:
            cur = conn.execute("SELECT * FROM experiences WHERE experience_id = ?;", (experience_id,))
            row = cur.fetchone()
            if row:
                return self._row_to_record(row)
            return None

    def get_by_source(self, source: str, source_id: str) -> ExperienceRecord | None:
        """Recupera uma experiência pela chave natural de proveniência (source, source_id)."""
        with self.connection() as conn:
            cur = conn.execute(
                "SELECT * FROM experiences WHERE source = ? AND source_id = ?;",
                (source, source_id),
            )
            row = cur.fetchone()
            if row:
                return self._row_to_record(row)
            return None

    def list_experiences(
        self,
        source: str | None = None,
        run_id: str | None = None,
        limit: int | None = None,
    ) -> list[ExperienceRecord]:
        """Lista experiências com ordenação cronológica determinística (decision_at ASC, experience_id ASC)."""
        query = "SELECT * FROM experiences WHERE 1=1"
        params: list[Any] = []

        if source is not None:
            query += " AND source = ?"
            params.append(source)
        if run_id is not None:
            query += " AND run_id = ?"
            params.append(run_id)

        query += " ORDER BY decision_at ASC, experience_id ASC"

        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        with self.connection() as conn:
            cur = conn.execute(query, params)
            return [self._row_to_record(r) for r in cur.fetchall()]

    def count(self, source: str | None = None, run_id: str | None = None) -> int:
        """Retorna contagem total de experiências registradas."""
        query = "SELECT COUNT(*) FROM experiences WHERE 1=1"
        params: list[Any] = []

        if source is not None:
            query += " AND source = ?"
            params.append(source)
        if run_id is not None:
            query += " AND run_id = ?"
            params.append(run_id)

        with self.connection() as conn:
            cur = conn.execute(query, params)
            return int(cur.fetchone()[0])

    def clear(self, source: str | None = None) -> int:
        """Remove experiências registradas (útil para testes ou limpeza controlada)."""
        with self.connection() as conn:
            if source:
                cur = conn.execute("DELETE FROM experiences WHERE source = ?;", (source,))
            else:
                cur = conn.execute("DELETE FROM experiences;")
            return cur.rowcount

    def export_to_csv(
        self,
        filepath: str | Path,
        source: str | None = None,
        run_id: str | None = None,
    ) -> Path:
        """Exporta experiências de forma determinística para arquivo CSV plano."""
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)

        records = self.list_experiences(source=source, run_id=run_id)
        if not records:
            dummy_record = ExperienceRecord(
                experience_id="dummy",
                source="dummy",
                source_id="dummy",
                run_id="dummy",
                decision=DecisionContext(
                    decision_at="2000-01-01T00:00:00+00:00",
                    candle_timestamp=0,
                    symbol="BTC/USDT",
                    timeframe="5m",
                    price=1.0,
                    strategy_name="SMA",
                    strategy_version="1.0",
                    strategy_parameters={},
                    signal="HOLD",
                    signal_reason="",
                    position_before="NONE",
                    risk_decision="HOLD",
                    risk_reason="",
                    risk_allowed=True,
                ),
            )
            fieldnames = list(dummy_record.to_dict().keys())
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
            return path

        fieldnames = list(records[0].to_dict().keys())
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for rec in records:
                row = rec.to_dict()
                if isinstance(row.get("strategy_parameters"), dict):
                    row["strategy_parameters"] = json.dumps(row["strategy_parameters"], sort_keys=True)
                writer.writerow(row)

        return path

    def export_to_json(
        self,
        filepath: str | Path,
        source: str | None = None,
        run_id: str | None = None,
    ) -> Path:
        """Exporta experiências de forma determinística para arquivo JSON estruturado."""
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)

        records = self.list_experiences(source=source, run_id=run_id)
        data = [rec.to_dict() for rec in records]

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        return path


def build_experience_id(source: str, source_id: str) -> str:
    """Gera um experience_id determinístico derivado da proveniência."""
    namespace = uuid.UUID("a3b8908a-8b1b-4d44-934d-17639f72782b")
    return str(uuid.uuid5(namespace, f"{source}:{source_id}"))


def create_experience_from_paper_cycle(
    cycle: Any,
    candle: Any | None = None,
    short_window: int = 5,
    long_window: int = 10,
    strategy_name: str = "SMA_CROSSOVER",
    strategy_version: str = "1.0.0",
    run_id: str = "paper_runner",
    source_id: str | None = None,
) -> ExperienceRecord:
    """Cria um ExperienceRecord a partir de um PaperCycleResult (Decision Experience ou Trade Entry)."""
    now_iso = datetime.now(timezone.utc).isoformat()
    cid = source_id or f"cycle_{cycle.closed_candle_timestamp}_{cycle.trade_action}"
    exp_id = build_experience_id("paper", cid)

    exec_price = float(cycle.executed_trade.price) if cycle.executed_trade else None
    exec_qty = float(cycle.executed_trade.quantity) if cycle.executed_trade else None
    exec_fee = float(cycle.executed_trade.fee) if cycle.executed_trade else None

    # Preço de referência
    ref_price = exec_price if exec_price is not None else (float(candle.close) if candle else 0.0)

    decision = DecisionContext(
        decision_at=now_iso,
        candle_timestamp=cycle.closed_candle_timestamp,
        symbol=cycle.symbol,
        timeframe=cycle.timeframe,
        price=ref_price if ref_price > 0 else 1.0,
        open=float(candle.open) if candle else None,
        high=float(candle.high) if candle else None,
        low=float(candle.low) if candle else None,
        close=float(candle.close) if candle else None,
        volume=float(candle.volume) if candle else None,
        strategy_name=strategy_name,
        strategy_version=strategy_version,
        strategy_parameters={"short_window": short_window, "long_window": long_window},
        signal=cycle.signal.value if hasattr(cycle.signal, "value") else str(cycle.signal),
        signal_reason=cycle.signal_reason,
        position_before=cycle.position.side,
        risk_decision=cycle.risk_decision.code.value if cycle.risk_decision else "UNKNOWN",
        risk_reason=cycle.risk_decision.reason if cycle.risk_decision else "",
        risk_allowed=cycle.risk_decision.allowed if cycle.risk_decision else False,
        execution_price=exec_price,
        execution_quantity=exec_qty,
        execution_fee=exec_fee,
    )

    # Se a ação foi encerramento (SELL executado), há outcome imediato
    outcome = None
    if cycle.executed_trade and cycle.executed_trade.side == "SELL":
        pnl = float(cycle.executed_trade.realized_pnl) if cycle.executed_trade.realized_pnl is not None else 0.0
        out_label = "WIN" if pnl > 0 else "LOSS" if pnl < 0 else "BREAK_EVEN"
        outcome = OutcomeContext(
            outcome_at=now_iso,
            exit_price=exec_price,
            realized_pnl=pnl,
            fees=exec_fee,
            outcome=out_label,
        )
    elif not decision.risk_allowed:
        outcome = OutcomeContext(
            outcome_at=now_iso,
            outcome="BLOCKED",
        )
    elif decision.signal == "HOLD":
        outcome = OutcomeContext(
            outcome_at=now_iso,
            outcome="HOLD",
        )

    return ExperienceRecord(
        experience_id=exp_id,
        source="paper",
        source_id=cid,
        run_id=run_id,
        decision=decision,
        outcome=outcome,
        created_at=now_iso,
    )


def create_experience_from_backtest_trade(
    trade: Any,
    symbol: str,
    timeframe: str,
    short_window: int,
    long_window: int,
    run_id: str = "backtest",
    source_id: str | None = None,
    candle_timestamp: int = 0,
    strategy_name: str = "SMA_CROSSOVER",
    strategy_version: str = "1.0.0",
) -> ExperienceRecord:
    """Cria um ExperienceRecord a partir de um trade fechado do Backtesting.py."""
    # trade pode ser pd.Series ou dict
    def _val(key: str, default: Any = None) -> Any:
        if hasattr(trade, "get"):
            return trade.get(key, default)
        if hasattr(trade, key):
            return getattr(trade, key)
        return default

    entry_price = float(_val("EntryPrice", 0.0))
    exit_price = float(_val("ExitPrice", 0.0))
    pnl = float(_val("PnL", 0.0))
    ret_pct = float(_val("ReturnPct", 0.0))

    entry_time = str(_val("EntryTime", datetime.now(timezone.utc).isoformat()))
    exit_time = str(_val("ExitTime", datetime.now(timezone.utc).isoformat()))
    duration = _val("Duration", None)
    duration_sec = duration.total_seconds() if hasattr(duration, "total_seconds") else None

    # Normalização de timestamps ISO
    try:
        dec_dt = _parse_iso_utc(entry_time)
        entry_iso = dec_dt.isoformat()
    except Exception:
        entry_iso = datetime.now(timezone.utc).isoformat()

    try:
        out_dt = _parse_iso_utc(exit_time)
        exit_iso = out_dt.isoformat()
    except Exception:
        exit_iso = entry_iso

    cid = source_id or f"bt_{entry_iso}_{entry_price}"
    exp_id = build_experience_id("backtest", cid)

    decision = DecisionContext(
        decision_at=entry_iso,
        candle_timestamp=candle_timestamp,
        symbol=symbol,
        timeframe=timeframe,
        price=entry_price,
        strategy_name=strategy_name,
        strategy_version=strategy_version,
        strategy_parameters={"short_window": short_window, "long_window": long_window},
        signal="BUY",
        signal_reason="Backtest strategy entry signal",
        position_before="NONE",
        risk_decision="ALLOWED",
        risk_reason="Backtest simulated execution",
        risk_allowed=True,
        execution_price=entry_price,
        execution_quantity=abs(float(_val("Size", 0.0))),
    )

    out_label = "WIN" if pnl > 0 else "LOSS" if pnl < 0 else "BREAK_EVEN"
    outcome = OutcomeContext(
        outcome_at=exit_iso,
        exit_price=exit_price,
        realized_pnl=pnl,
        realized_return=ret_pct,
        trade_duration=duration_sec,
        outcome=out_label,
    )

    return ExperienceRecord(
        experience_id=exp_id,
        source="backtest",
        source_id=cid,
        run_id=run_id,
        decision=decision,
        outcome=outcome,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
