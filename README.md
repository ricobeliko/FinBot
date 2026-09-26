# FinBot

Bot local para estudo, validação e automação de estratégias de negociação de ativos e criptoativos.

---

## STATUS ATUAL

```text
STATUS ATUAL:
FASE 6 — Risk Engine.
No real trading functionality exists.
```

O projeto concluiu a **FASE 6 (Risk Engine)**. O FinBot agora possui uma camada explícita, determinística e obrigatória de gestão de risco intermediária entre a estratégia e o broker simulado (`Market Data -> Strategy -> Signal -> Risk Engine -> Paper Broker`). O motor de risco opera 100% offline (sem CCXT, sem rede) e controla: tamanho máximo de posição (100 USDT), limite de perda diária realizada (50 USDT), proteção de Stop Loss defensivo (2.0%), cooldown de 1 candle fechado pós-saída e Kill Switch persistente no SQLite com controle CLI.

> **Importante**: Paper Trading utiliza capital exclusivamente fictício. Nenhuma ordem real é enviada e nenhuma credencial de API é utilizada.

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

6. Executar o Paper Trading com Risk Engine:
   ```powershell
   python -m finbot.paper
   ```

   Consultar o status da conta, histórico e métricas de risco (offline):
   ```powershell
   python -m finbot.paper --status
   ```

   Ativar ou desativar o Kill Switch de emergência (offline):
   ```powershell
   python -m finbot.paper --kill-switch on
   python -m finbot.paper --kill-switch off
   ```

   Resetar a conta, histórico simulado e estado do Risk Engine:
   ```powershell
   python -m finbot.paper --reset --yes
   ```

---

## Roadmap Resumido

- **FASE 0 — Foundation** (concluída): Estrutura base, documentação e aplicação mínima.
- **FASE 1 — Python Core** (concluída): Configuração local e logging básico.
- **FASE 2 — Market Monitor** (concluída): Integração CCXT somente leitura de dados públicos.
- **FASE 3 — Strategy Engine** (concluída): Motor de sinais determinísticos (SMA Crossover).
- **FASE 4 — Backtesting** (concluída): Simulação reproduzível sobre dataset local e métricas.
- **FASE 5 — Paper Trading** (concluída): Simulação de ordens e carteira virtual com SQLite.
- **FASE 6 — Risk Engine** (concluída): Limites estritos, stop loss, cooldown e kill switch.
- **FASE 7 — Dashboard Local**: Acompanhamento visual via localhost.
- **FASE 8 — Integração Live**: Operações reais (bloqueado por padrão).
- **FASE 9 — Estabilidade**: Resiliência e recuperação de conexões.
- **FASE 10 — Empacotamento/Transferência**: Preparação final para PC de destino.

Consulte `ROADMAP.md` para o detalhamento completo.
