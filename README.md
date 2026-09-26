# FinBot

Bot local para estudo, validação e automação de estratégias de negociação de ativos e criptoativos.

---

## STATUS ATUAL

```text
STATUS ATUAL:
FASE 4 — Backtesting.
No real trading functionality exists.
```

O projeto concluiu a **FASE 4 (Backtesting)**. Além da consulta a dados públicos de mercado via CCXT (Binance Spot, BTC/USDT) e cálculo determinístico de sinais operacionais (`BUY`, `SELL`, `HOLD`), o FinBot agora executa backtests históricos reproduzíveis via Backtesting.py sobre datasets locais com métricas consolidadas (retorno total, Buy & Hold, trades, win rate, drawdown e profit factor).

> **Importante**: Backtest é estritamente simulação histórica local (SIMULATION ONLY). Nenhuma ordem, carteira, saldo real ou conectividade de envio a exchanges existe.

---

## Objetivo

Fornecer uma plataforma local-first, enxuta, determinística e segura para testes quantitativos e execução controlada de estratégias financeiras, sem complexidades de nuvem ou microserviços.

---

## Arquitetura Planejada

```text
Market Data ──▶ Strategy ──▶ Risk Manager ──▶ Broker ──▶ Storage
```

- **Local-first**: Execução local no Windows.
- **Segurança de Fluxo**: A estratégia nunca se comunica diretamente com a exchange; toda ordem passa pelo `Risk Manager`.
- **Modos Futuros**: `MONITOR`, `BACKTEST`, `PAPER` e `LIVE` (bloqueado por padrão).

---

## Requisitos

- Windows
- Python 3.12 (>=3.12,<3.13)
- Git (apenas local)

---

## Instalação e Execução Local

1. Navegar até o diretório:
   ```powershell
   cd D:\Projetos\FinBot
   ```

2. Ativar o ambiente virtual:
   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```

3. Instalar o projeto localmente em modo editável com dependências:
   ```powershell
   python -m pip install -e .
   ```

4. Executar o Market Monitor:
   ```powershell
   python -m finbot.main
   ```

   Saída esperada:
   ```text
   FinBot
   Environment: local
   Trading mode: disabled
   Status: running

   Exchange: binance
   Symbol: BTC/USDT

   Last price: <valor_atual>
   Candles loaded: 20

   Strategy:
   SMA 5 / SMA 10

   Short MA: <valor_curto>
   Long MA: <valor_longo>

   Signal: HOLD (ou BUY / SELL conforme o mercado)
   Reason: <motivo_do_sinal>

   Trading: disabled
   ```

5. Executar o Backtest histórico reproduzível:
   ```powershell
   python -m finbot.backtest
   ```

   Saída esperada:
   ```text
   ==================================================
   FinBot Backtest
   ==================================================

   Exchange: binance
   Symbol: BTC/USDT
   Timeframe: 5m
   Candles: 500
   Period: 2026-09-25 02:25:00 -> 2026-09-26 20:00:00

   Strategy:
   SMA 5 / SMA 10

   Initial cash:
   10000.00 USDT

   Commission assumption:
   0.10% (simulation assumption)

   Results:

   Final equity: 9366.42 USDT
   Return: -6.34%
   Buy & Hold: -0.77%
   Trades: 29 (Wins: 3, Losses: 26)
   Win rate: 10.34%
   Max drawdown: -6.34%
   Profit factor: 0.07

   Trading mode:
   SIMULATION ONLY

   No real orders were sent.
   ==================================================
   ```

---

## Roadmap Resumido

- **FASE 0 — Foundation** (concluída): Estrutura base, documentação e aplicação mínima.
- **FASE 1 — Python Core** (concluída): Configuração local e logging básico.
- **FASE 2 — Market Monitor** (concluída): Integração CCXT somente leitura de dados públicos.
- **FASE 3 — Strategy Engine** (concluída): Motor de sinais determinísticos (SMA Crossover).
- **FASE 4 — Backtesting** (concluída): Simulação reproduzível sobre dataset local e métricas.
- **FASE 5 — Paper Trading**: Simulação de ordens e carteira virtual com SQLite.
- **FASE 6 — Risk Engine**: Limites, validações e kill switch.
- **FASE 7 — Dashboard Local**: Acompanhamento visual via localhost.
- **FASE 8 — Integração Live**: Operações reais (bloqueado por padrão).
- **FASE 9 — Estabilidade**: Resiliência e recuperação de conexões.
- **FASE 10 — Empacotamento/Transferência**: Preparação final para PC de destino.

Consulte `ROADMAP.md` para o detalhamento completo.
