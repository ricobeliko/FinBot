# FinBot

Bot local para estudo, validação e automação de estratégias de negociação de ativos e criptoativos.

---

## STATUS ATUAL

```text
STATUS ATUAL:
FASE 7.6 — Paper Soak Test (IN PROGRESS).
No real trading functionality exists.
```

O projeto está na **FASE 7.6 (Paper Soak Test)**. O FinBot opera ciclos periódicos automáticos de Paper Trading (a cada 1 minuto) através do Windows Task Scheduler com execução one-shot, telemetria atômica no SQLite (`data/finbot_paper.sqlite3`), rotação de logs e isolamento contra falhas de rede. O painel visual em Streamlit (`http://127.0.0.1:8501`) e os comandos CLI (`--status` e `--soak-status`) exibem a saúde do runner (`RECENT` vs `STALE`), ciclos de sucesso/falha, patrimônio estimado, posições, P/L e métricas de risco de forma 100% Read-Only e local.

> **Importante**: Paper Trading utiliza capital exclusivamente fictício. O dashboard opera exclusivamente em modo leitura, sem capacidade técnica de enviar ordens reais ou modificar a carteira.

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
   # ou com foco na telemetria do soak test:
   python -m finbot.paper --soak-status
   ```

   Ativar ou desativar o Kill Switch de emergência (offline):
   ```powershell
   python -m finbot.paper --kill-switch on
   python -m finbot.paper --kill-switch off
   ```

7. Executar o Dashboard Visual Local (FASE 7):
   ```powershell
   streamlit run src/finbot/dashboard.py --server.address=127.0.0.1
   # ou via script:
   powershell -ExecutionPolicy Bypass -File scripts\run_dashboard.ps1
   ```
   Acesse no navegador: `http://127.0.0.1:8501`
   Painel 100% Read-Only e local (localhost).

8. Automação e Diagnóstico Local (FASE 7.5 / 7.6):
   ```powershell
   # Diagnóstico de integridade local (Python, SQLite, Paper Status, Git e Task Scheduler):
   powershell -ExecutionPolicy Bypass -File scripts\check_finbot.ps1

   # Executar ciclo individual de Paper Trading:
   powershell -ExecutionPolicy Bypass -File scripts\run_paper.ps1

   # Instalar tarefa agendada no Windows Task Scheduler (ciclos a cada 1m com IgnoreNew):
   powershell -ExecutionPolicy Bypass -File scripts\install_paper_task.ps1

   # Remover tarefa agendada:
   powershell -ExecutionPolicy Bypass -File scripts\remove_paper_task.ps1
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
- **FASE 7A — Dashboard Local Visual** (concluída): Acompanhamento visual via Streamlit (localhost).
- **FASE 7.5 — Automated Paper Runner** (concluída): Agendamento nativo Windows Task Scheduler (1m) e observabilidade.
- **FASE 7.6 — Paper Soak Test** (em andamento): Observação contínua de 72 horas para validação de estabilidade.
- **FASE 7B — Dashboard Mobile-Friendly**: Refinamento e ergonomia para telas menores.
- **FASE 7C — Acesso Remoto Seguro**: Avaliação de acesso seguro read-only.
- **FASE 8 — Integração Live**: Operações reais (bloqueado por padrão).
- **FASE 9 — Estabilidade**: Resiliência e recuperação de conexões.
- **FASE 10 — Instalação no PC Definitivo**: Preparação e provisionamento final.

Consulte `ROADMAP.md` para o detalhamento completo.
