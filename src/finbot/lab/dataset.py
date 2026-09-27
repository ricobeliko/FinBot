"""Módulo de carregamento e particionamento cronológico de datasets para o FinBot Lab.

Garante que os dados sejam estritamente divididos na ordem temporal (Train -> Validation -> Test)
sem shuffle, sem vazamento de informação futura (look-ahead bias) e com zero sobreposição.
"""

import hashlib
from pathlib import Path
from typing import Any
import pandas as pd

from finbot.backtest import candles_to_dataframe, load_dataset_snapshot
from finbot.lab.models import ChronologicalSplit, SplitRatio


def compute_file_hash(filepath: str | Path) -> str:
    """Calcula o hash SHA-256 do arquivo para auditoria de integridade."""
    path = Path(filepath)
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def load_lab_dataset(filepath: str | Path) -> tuple[dict[str, Any], pd.DataFrame]:
    """Carrega dataset local estritamente offline via snapshot salvo.

    Reutiliza a estrutura e leitor existentes em `finbot.backtest`.
    Zero chamadas de rede ou APIs privadas.
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Arquivo de dataset não encontrado para o Lab: {path}")

    metadata, candles = load_dataset_snapshot(path)
    df = candles_to_dataframe(candles)

    meta_dict = {
        "exchange": metadata.exchange,
        "symbol": metadata.symbol,
        "timeframe": metadata.timeframe,
        "candle_count": metadata.candle_count,
        "start_timestamp": metadata.start_timestamp,
        "end_timestamp": metadata.end_timestamp,
        "start_datetime": metadata.start_datetime,
        "end_datetime": metadata.end_datetime,
        "downloaded_at": metadata.downloaded_at,
        "file_hash": compute_file_hash(path),
    }

    return meta_dict, df


def split_chronological(
    df: pd.DataFrame,
    ratio: SplitRatio = SplitRatio(),
    min_candles_per_partition: int = 10,
) -> ChronologicalSplit:
    """Divide um DataFrame de candles em 3 partições cronológicas sem shuffle.

    Particionamento estrito:
    1. Train (mais antigo)
    2. Validation (intermediário)
    3. Test (mais recente, out-of-sample)

    Garante que:
    - O DataFrame original nunca é alterado (cópias explícitas).
    - Não há overlap de candles ou timestamps.
    - A soma dos tamanhos das partições é exatamente igual ao total original.
    """
    total = len(df)
    min_total = min_candles_per_partition * 3
    if total < min_total:
        raise ValueError(
            f"Dataset insuficiente para split cronológico: {total} candles fornecidos, "
            f"mínimo necessário é {min_total} ({min_candles_per_partition} por partição)."
        )

    # Cálculo dos cortes respeitando as proporções
    train_count = int(round(total * ratio.train))
    val_count = int(round(total * ratio.validation))
    test_count = total - (train_count + val_count)

    # Ajuste fino defensivo para garantir tamanho mínimo em cada partição
    if train_count < min_candles_per_partition:
        train_count = min_candles_per_partition
        test_count = total - (train_count + val_count)
    if val_count < min_candles_per_partition:
        val_count = min_candles_per_partition
        test_count = total - (train_count + val_count)
    if test_count < min_candles_per_partition:
        deficit = min_candles_per_partition - test_count
        test_count = min_candles_per_partition
        train_count -= deficit

    val_start = train_count
    val_end = train_count + val_count
    test_start = val_end

    train_df = df.iloc[:train_count].copy()
    val_df = df.iloc[val_start:val_end].copy()
    test_df = df.iloc[test_start:].copy()

    start_time = str(df.index[0]) if len(df) > 0 else ""
    end_time = str(df.index[-1]) if len(df) > 0 else ""

    return ChronologicalSplit(
        train_df=train_df,
        validation_df=val_df,
        test_df=test_df,
        train_count=len(train_df),
        val_count=len(val_df),
        test_count=len(test_df),
        total_count=total,
        start_time=start_time,
        end_time=end_time,
    )
