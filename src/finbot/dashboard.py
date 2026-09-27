"""Dashboard visual local e responsivo do FinBot (FASE 7).

Interface gráfica construída com Streamlit para acompanhamento em tempo real
do estado operacional, carteira simulada, histórico de trades e métricas de risco.

PRINCÍPIOS ARQUITETURAIS:
- 100% Local-first e Read-Only (somente leitura).
- NENHUM botão ou ação para executar trades, alterar saldos ou modificar o Risk Engine.
- Funciona perfeitamente offline com dados persistidos no SQLite.
- Consulta preço público ao vivo de forma defensiva (fallback gracioso caso offline).
- Responsivo: adaptável para visualização em desktop e smartphone.
"""

from datetime import datetime, timezone
from decimal import Decimal
import os
import sys

import pandas as pd
import streamlit as st

from finbot.config import Config, get_config
from finbot.metrics import (
    calculate_paper_equity,
    calculate_performance_metrics,
    calculate_runner_freshness,
    calculate_unrealized_pnl,
    get_cumulative_pnl_series,
)
from finbot.risk import is_cooldown_active
from finbot.storage import PaperStorage


def fetch_live_price_safely(symbol: str, exchange_id: str) -> float | None:
    """Consulta o preço público mais recente via CCXT de forma segura.

    Retorna None em caso de falha de conexão ou ambiente offline,
    garantindo que o painel principal nunca trave.
    """
    try:
        from finbot.exchange import close_exchange, create_exchange, fetch_ticker

        ex = create_exchange(exchange_id)
        try:
            ticker = fetch_ticker(ex, symbol)
            return ticker.last
        finally:
            close_exchange(ex)
    except Exception:
        return None


def run_dashboard() -> None:
    """Renderiza o dashboard visual local do FinBot."""
    st.set_page_config(
        page_title="FinBot — Dashboard",
        page_icon="📈",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    config = get_config()
    storage = PaperStorage(db_path=config.paper_db_path)
    storage.init_db(initial_cash=Decimal(str(config.paper_initial_cash)))

    # Coleta de dados persistidos no SQLite (100% offline)
    account = storage.get_account()
    position = storage.get_position()
    trades = storage.get_trades(limit=50)
    metrics = calculate_performance_metrics(trades)
    last_processed_candle = storage.get_last_processed_candle_timestamp()
    kill_switch_active = storage.get_kill_switch(default=config.risk_kill_switch)
    daily_realized_loss = storage.get_daily_realized_loss()
    last_closed_ts = storage.get_last_closed_trade_candle_timestamp()
    last_risk_block = storage.get_last_risk_block()
    last_signal_info = storage.get_last_signal()
    cycle_info = storage.get_last_cycle_info()

    # Preço público atual (com fallback caso offline)
    live_price = fetch_live_price_safely(config.symbol, config.exchange_id)
    current_price_dec = Decimal(str(live_price)) if live_price is not None else None

    # Métricas patrimoniais
    estimated_equity = calculate_paper_equity(account, position, current_price_dec)
    unrealized_info = calculate_unrealized_pnl(position, current_price_dec)

    # -------------------------------------------------------------------------
    # BARRA LATERAL (SIDEBAR) — Informações e Configuração
    # -------------------------------------------------------------------------
    with st.sidebar:
        st.title("🤖 FinBot Control")
        st.caption("Ambiente de Operação Local")

        st.divider()

        st.subheader("Configuração Ativa")
        st.text(f"Ativo: {config.symbol}")
        st.text(f"Exchange: {config.exchange_id.upper()} (Spot)")
        st.text(f"Estratégia: SMA {config.short_window}/{config.long_window}")
        st.text(f"Timeframe: {config.paper_timeframe}")
        st.text(f"Notional Trade: {config.paper_trade_notional:.2f} USDT")

        st.divider()

        st.subheader("Segurança Patrimonial")
        st.success("Trading Real: DISABLED")
        st.info("Credenciais API: NONE")
        st.caption("Modo de Operação: READ-ONLY")

        st.divider()

        if st.button("🔄 Atualizar Dados", use_container_width=True):
            st.rerun()

        st.caption(f"Banco: `{config.paper_db_path}`")
        st.caption("FinBot v0.1.0 — FASE 7")

    # -------------------------------------------------------------------------
    # CABEÇALHO PRINCIPAL
    # -------------------------------------------------------------------------
    header_col1, header_col2 = st.columns([3, 1])
    with header_col1:
        st.title("📊 FinBot — Paper Trading Dashboard")
        st.markdown(
            "Painel local de monitoramento quantitativo, histórico operacional e limites de risco."
        )
    with header_col2:
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown(
            """
            <div style="background-color: #1e293b; padding: 10px; border-radius: 8px; border: 1px solid #334155; text-align: center;">
                <span style="color: #38bdf8; font-weight: bold;">● PAPER MODE</span><br>
                <small style="color: #94a3b8;">EXECUTION: ONE-SHOT PAPER</small>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("---")

    # -------------------------------------------------------------------------
    # LINHA 1: CARDS PRINCIPAIS DE PATRIMÔNIO E SALDO
    # -------------------------------------------------------------------------
    pnl_delta = f"{metrics.total_realized_pnl:+,.2f} USDT"
    c1, c2, c3, c4 = st.columns(4)

    with c1:
        equity_sub = "100% USDT" if position.side == "NONE" else "USDT + BTC a mercado"
        st.metric(
            label="Patrimônio Estimado",
            value=f"{estimated_equity:,.2f} USDT",
            help=f"Saldo total consolidado ({equity_sub})",
        )

    with c2:
        st.metric(
            label="Saldo USDT Disponível",
            value=f"{account.usdt_balance:,.2f} USDT",
        )

    with c3:
        btc_val_str = f"≈ {(account.btc_balance * current_price_dec):,.2f} USDT" if current_price_dec else ""
        st.metric(
            label="Saldo BTC Paper",
            value=f"{account.btc_balance:.8f} BTC",
            delta=btc_val_str if btc_val_str else None,
            delta_color="off",
        )

    with c4:
        st.metric(
            label="P/L Realizado Acumulado",
            value=pnl_delta,
            delta=f"{metrics.closed_trades} trades fechados",
            delta_color="normal" if metrics.total_realized_pnl >= Decimal("0") else "inverse",
        )

    # -------------------------------------------------------------------------
    # LINHA 2: ESTADO DA POSIÇÃO E PERFORMANCE
    # -------------------------------------------------------------------------
    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
    c5, c6, c7, c8 = st.columns(4)

    with c5:
        if position.side == "LONG":
            pos_label = f"LONG ({position.quantity:.6f} BTC)"
            pos_desc = f"@ {position.entry_price:,.2f} USDT"
        else:
            pos_label = "NONE"
            pos_desc = "Sem exposição aberta"
        st.metric(label="Posição Atual", value=pos_label, delta=pos_desc, delta_color="off")

    with c6:
        if unrealized_info is not None:
            u_usdt, u_pct = unrealized_info
            st.metric(
                label="P/L Não Realizado",
                value=f"{u_usdt:+,.2f} USDT",
                delta=f"{u_pct:+.2f}%",
                delta_color="normal" if u_usdt >= Decimal("0") else "inverse",
            )
        else:
            st.metric(label="P/L Não Realizado", value="N/A", delta="Sem posição ativa", delta_color="off")

    with c7:
        st.metric(
            label="Taxa de Acerto (Win Rate)",
            value=f"{metrics.win_rate_pct:.1f}%",
            delta=f"{metrics.winning_trades}W / {metrics.losing_trades}L",
            delta_color="off",
        )

    with c8:
        st.metric(
            label="Total de Taxas Pagas",
            value=f"{metrics.total_fees:,.2f} USDT",
            delta="0.10% por ordem",
            delta_color="off",
        )

    st.markdown("---")

    # -------------------------------------------------------------------------
    # SEÇÃO: GRÁFICO DE P/L CUMULATIVO E DESEMPENHO
    # -------------------------------------------------------------------------
    chart_col, status_col = st.columns([2, 1])

    with chart_col:
        st.subheader("📈 Evolução do P/L Realizado Cumulativo")
        pnl_series = get_cumulative_pnl_series(trades)

        if len(pnl_series) > 0:
            df_chart = pd.DataFrame(pnl_series)
            df_chart["Trade #"] = df_chart["trade_seq"]
            df_chart["P/L Cumulativo (USDT)"] = df_chart["cumulative_pnl"]
            st.line_chart(df_chart, x="Trade #", y="P/L Cumulativo (USDT)", color="#38bdf8")
            st.caption(
                "Nota: Gráfico gerado estritamente a partir do histórico de trades reais fechados (sem dados artificiais interpolados)."
            )
        else:
            st.info(
                "ℹ️ Nenhum trade fechado registrado até o momento. "
                "O gráfico de P/L acumulado será gerado automaticamente conforme operações forem executadas."
            )

    with status_col:
        st.subheader("⚡ Status Operacional & Paper Runner")

        # Avaliação de frescor do Paper Runner
        last_cycle_ts = cycle_info.get("timestamp")
        freshness, elapsed = calculate_runner_freshness(last_cycle_ts)

        if freshness == "RECENT":
            elapsed_desc = f"há {int(elapsed)}s" if elapsed is not None else ""
            st.success(f"🟢 **Paper Runner: ACTIVE RECENTLY** ({elapsed_desc})")
        elif freshness == "STALE":
            mins = int(elapsed / 60) if elapsed is not None else 0
            st.warning(f"🟠 **Paper Runner: STALE** (há ~{mins} min sem ciclo)")
        else:
            st.info("⚪ **Paper Runner: NEVER RUN** (nenhum ciclo registrado)")

        candle_str = "Aguardando ciclo..."
        if last_processed_candle:
            dt_candle = datetime.fromtimestamp(last_processed_candle / 1000, tz=timezone.utc)
            candle_str = dt_candle.strftime("%Y-%m-%d %H:%M:%S UTC")

        sig_val = last_signal_info.get("signal", "Nenhum") if last_signal_info else "Nenhum"
        sig_reason = last_signal_info.get("reason", "") if last_signal_info else "Aguardando ciclo"

        last_cycle_disp = cycle_info.get("timestamp")[:19].replace("T", " ") + " UTC" if cycle_info.get("timestamp") else "N/A"
        last_succ_disp = cycle_info.get("successful_timestamp")[:19].replace("T", " ") + " UTC" if cycle_info.get("successful_timestamp") else "N/A"
        last_res = cycle_info.get("result") or "Nenhum"

        st.markdown(
            f"""
            - **Modo de Execução:** `ONE-SHOT (Task Scheduler / Manual)`
            - **Último Ciclo:** `{last_cycle_disp}`
            - **Último Sucesso:** `{last_succ_disp}`
            - **Resultado do Ciclo:** `{last_res}`
            - **Último Candle Avaliado:** `{candle_str}`
            - **Último Sinal Gerado:** `{sig_val}` (`{sig_reason}`)
            - **Preço Público Observado:** `{(f'{live_price:,.2f} USDT' if live_price else 'Indisponível (Offline)')}`
            - **Última Atualização Carteira:** `{account.updated_at[:19].replace('T', ' ')} UTC`
            """
        )

    st.markdown("---")

    # -------------------------------------------------------------------------
    # SEÇÃO: CONTROLE E GESTÃO DE RISCO (RISK ENGINE)
    # -------------------------------------------------------------------------
    st.subheader("🛡️ Controle e Gestão de Risco (Risk Engine)")

    risk_c1, risk_c2, risk_c3, risk_c4 = st.columns(4)

    with risk_c1:
        if kill_switch_active:
            st.error("🚨 **Kill Switch: ATIVO**\n\nNovos BUYs estão bloqueados.")
        else:
            st.success("✅ **Kill Switch: INATIVO**\n\nOperação normal autorizada.")

    with risk_c2:
        max_daily = Decimal(str(config.risk_max_daily_loss))
        st.metric(
            label="Perda Realizada Hoje (UTC)",
            value=f"{daily_realized_loss:+.2f} USDT",
            delta=f"Limite: -{max_daily:.2f} USDT",
            delta_color="normal" if daily_realized_loss > -max_daily else "inverse",
        )

    with risk_c3:
        st.metric(
            label="Limite Máximo de Posição",
            value=f"{config.risk_max_position_notional:.2f} USDT",
            delta="1 posição simultânea",
            delta_color="off",
        )

    with risk_c4:
        # Avaliação de Cooldown
        timeframe_ms = 60000
        if config.paper_timeframe.endswith("m"):
            timeframe_ms = int(config.paper_timeframe[:-1]) * 60000
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        cooldown_status = False
        if last_closed_ts is not None:
            cooldown_status = is_cooldown_active(
                last_closed_trade_candle_ts=last_closed_ts,
                current_candle_ts=now_ms,
                cooldown_candles=config.risk_cooldown_candles,
                timeframe_ms=timeframe_ms,
            )

        cd_label = "ATIVO" if cooldown_status else "INATIVO"
        st.metric(
            label="Cooldown Pós-Saída",
            value=cd_label,
            delta=f"{config.risk_cooldown_candles} candle(s) fechados",
            delta_color="inverse" if cooldown_status else "off",
        )

    if last_risk_block:
        st.warning(f"⚠️ **Último bloqueio registrado pelo Risk Engine:** {last_risk_block}")

    st.markdown("---")

    # -------------------------------------------------------------------------
    # SEÇÃO: HISTÓRICO DE TRADES RECENTES
    # -------------------------------------------------------------------------
    st.subheader("📋 Histórico Recente de Trades Simulados")

    if len(trades) > 0:
        trades_data = []
        for t in trades[:20]:
            pnl_str = f"{t.realized_pnl:+.2f}" if t.realized_pnl is not None else "-"
            exit_str = t.exit_reason if t.exit_reason else ("-" if t.side == "BUY" else "STRATEGY_SIGNAL")
            trades_data.append(
                {
                    "ID": t.id,
                    "Data/Hora UTC": t.timestamp[:19].replace("T", " "),
                    "Lado": t.side,
                    "Preço (USDT)": float(t.price),
                    "Qtd (BTC)": float(t.quantity),
                    "Notional (USDT)": float(t.notional),
                    "Taxa (USDT)": float(t.fee),
                    "P/L Realizado (USDT)": pnl_str,
                    "Motivo de Saída": exit_str,
                }
            )

        df_trades = pd.DataFrame(trades_data)
        st.dataframe(df_trades, use_container_width=True, hide_index=True)
    else:
        st.info("Nenhuma operação executada ainda na conta de Paper Trading.")

    # -------------------------------------------------------------------------
    # RODAPÉ
    # -------------------------------------------------------------------------
    st.markdown("<br><br>", unsafe_allow_html=True)
    st.caption(
        "FinBot v0.1.0 • Arquitetura Local-first • Execução 100% em localhost (127.0.0.1) • "
        "Sem custódia de chaves privadas • Zero ordens reais enviadas a exchanges."
    )


if __name__ == "__main__":
    run_dashboard()
