"""FinBot Lab — Dashboard Visual Local e Isolado para Análise Quantitativa.

Interface gráfica via Streamlit para exploração de varredura de parâmetros (parameter sweep),
análise de overfitting (Train vs Validation vs Test) e screening de candidatos.
Executa de forma isolada na porta 8502 e opera 100% em modo READ-ONLY.
"""

import json
from pathlib import Path
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="FinBot Lab — Research & Screening",
    page_icon="🔬",
    layout="wide",
)

RESULTS_DIR = Path("data/lab/results")


def list_available_runs() -> list[tuple[str, Path, Path]]:
    """Busca pares de CSV e JSON de resultados no diretório do Lab."""
    if not RESULTS_DIR.exists():
        return []

    csv_files = sorted(RESULTS_DIR.glob("sma_sweep_*.csv"), reverse=True)
    runs = []
    for csv_file in csv_files:
        json_file = csv_file.with_suffix(".json")
        if json_file.exists():
            label = csv_file.stem.replace("sma_sweep_", "")
            runs.append((label, csv_file, json_file))
    return runs


def load_run_data(csv_file: Path, json_file: Path) -> tuple[pd.DataFrame, dict]:
    """Carrega dados tabulares e metadados de uma execução do Lab."""
    df = pd.read_csv(csv_file)
    with open(json_file, "r", encoding="utf-8") as f:
        meta = json.load(f)
    return df, meta


def main() -> None:
    st.title("🔬 FinBot Lab — Quantitative Research & Screening")
    st.caption("Ambiente isolado de pesquisa quantitativa e proteção contra overfitting | 100% Read-Only")

    st.warning(
        "⚠️ **DATASET MODE: EXPLORATORY / ENGINEERING VALIDATION**  \n"
        "Os resultados apresentados destinam-se estritamente à validação de engenharia do pipeline do Lab. "
        "Snapshots históricos curtos não constituem prova de robustez estatística. "
        "O FinBot Lab opera isolado e **jamais altera a estratégia operacional**."
    )

    runs = list_available_runs()
    if not runs:
        st.info(
            "Nenhuma execução do Lab encontrada em `data/lab/results/`.  \n"
            "Execute uma varredura via terminal para visualizar os resultados aqui:  \n"
            "```powershell\npython -m finbot.lab --preset smoke\n```"
        )
        return

    # Sidebar para seleção de execução e filtros
    st.sidebar.header("Configurações do Lab")
    run_options = {f"{label} ({Path(p[1]).name})": p for label, p in zip([r[0] for r in runs], runs, strict=False)}
    selected_label = st.sidebar.selectbox("Execução Selecionada", list(run_options.keys()))
    _, csv_path, json_path = run_options[selected_label]

    df, meta = load_run_data(csv_path, json_path)

    # Exibição de KPIs da Execução
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Dataset", f"{meta.get('symbol', 'N/A')} ({meta.get('timeframe', 'N/A')})")
    with col2:
        st.metric("Preset", f"{str(meta.get('preset', 'N/A')).upper()} ({meta.get('total_combinations', 0)} pares)")
    with col3:
        st.metric("Workers", f"{meta.get('workers', 1)} processos")
    with col4:
        st.metric("Tempo Decorrido", f"{meta.get('elapsed_seconds', 0.0):.2f}s")

    st.markdown("---")

    # Filtros interativos
    st.sidebar.subheader("Filtros de Candidatos")
    min_short = int(df["short_window"].min())
    max_short = int(df["short_window"].max())
    min_long = int(df["long_window"].min())
    max_long = int(df["long_window"].max())

    short_range = st.sidebar.slider("Faixa SMA Curta", min_short, max_short, (min_short, max_short))
    long_range = st.sidebar.slider("Faixa SMA Longa", min_long, max_long, (min_long, max_long))

    max_trades = int(df["train_trades"].max())
    min_trades = st.sidebar.slider("Mínimo de Trades (Treino)", 0, max_trades, 0)

    sort_metric = st.sidebar.selectbox(
        "Ordenar Screening por",
        ["train_return_pct", "val_return_pct", "test_return_pct", "train_max_drawdown", "train_profit_factor"],
        index=0,
    )

    filtered_df = df[
        (df["short_window"] >= short_range[0])
        & (df["short_window"] <= short_range[1])
        & (df["long_window"] >= long_range[0])
        & (df["long_window"] <= long_range[1])
        & (df["train_trades"] >= min_trades)
    ].copy()

    filtered_df.sort_values(by=sort_metric, ascending=False, inplace=True)

    # Visualização de Gráficos de Degradação / Overfitting
    st.subheader("📊 Diagnóstico de Overfitting (Treino vs Teste Out-of-Sample)")
    c1, c2 = st.columns([1, 1])

    with c1:
        st.markdown("**Dispersão: Retorno no Treino vs Retorno no Teste**")
        st.scatter_chart(
            filtered_df,
            x="train_return_pct",
            y="test_return_pct",
            color="short_window",
            height=320,
        )

    with c2:
        st.markdown("**Top 10 Candidatos — Comparativo de Retorno por Partição**")
        top10 = filtered_df.head(10).copy()
        top10["candidato"] = "SMA " + top10["short_window"].astype(str) + "/" + top10["long_window"].astype(str)
        chart_data = top10.set_index("candidato")[["train_return_pct", "val_return_pct", "test_return_pct"]]
        chart_data.columns = ["Treino (%)", "Validação (%)", "Teste (%)"]
        st.bar_chart(chart_data, height=320)

    st.markdown("---")

    # Tabela detalhada de resultados
    st.subheader(f"📋 Tabela de Screening ({len(filtered_df)} candidatos filtrados)")

    display_cols = [
        "short_window",
        "long_window",
        "train_return_pct",
        "val_return_pct",
        "test_return_pct",
        "train_max_drawdown",
        "val_max_drawdown",
        "test_max_drawdown",
        "train_trades",
        "val_trades",
        "test_trades",
        "train_profit_factor",
        "val_profit_factor",
        "test_profit_factor",
    ]

    st.dataframe(
        filtered_df[display_cols].style.format({
            "train_return_pct": "{:+.2f}%",
            "val_return_pct": "{:+.2f}%",
            "test_return_pct": "{:+.2f}%",
            "train_max_drawdown": "{:.2f}%",
            "val_max_drawdown": "{:.2f}%",
            "test_max_drawdown": "{:.2f}%",
            "train_profit_factor": "{:.2f}",
            "val_profit_factor": "{:.2f}",
            "test_profit_factor": "{:.2f}",
        }),
        use_container_width=True,
    )


if __name__ == "__main__":
    main()
