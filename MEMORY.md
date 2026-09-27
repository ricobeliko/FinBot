# FinBot Memory

## Estado atual
FASE 7.8 — FinBot Lab: Auditoria Metodológica + Dataset Histórico Maior concluída no Notebook.

### FinBot Lab (Pesquisa & Otimização Offline)
- Arquitetura isolada em `src/finbot/lab/` para backtest paralelo e mitigação de overfitting
- Auditoria metodológica concluída: partições independentes (Train 60%, Val 20%, Test 20%), capital reiniciado a 10.000 USDT, posição zerada no início de cada split, zero transbordo de posições
- Warm-up interno: primeiros `long_window` candles de cada split atuam como aquecimento emitindo HOLD, prevenindo contaminação de Buy & Hold da partição anterior
- Ranqueamento estritamente cego: candidatos ordenados unicamente pelo Treino; Validação e Teste atuam exclusivamente como out-of-sample
- Dataset histórico ampliado: 10.000 candles de 5m (Binance Spot BTC/USDT, ~34.7 dias) baixados via `scripts/download_dataset.py` e congelados em `data/backtest/binance_BTCUSDT_5m_10000.json` (1.7 MB)
- Dataset original congelado de 500 candles preservado intacto
- Dashboard analítico separado em `src/finbot/lab_dashboard.py` (porta 8502, 100% Read-Only)
- 100 testes unitários automatizados determinísticos passando
- Zero autoridade operacional: o Lab NÃO altera o bot operacional nem acessa `data/finbot_paper.sqlite3`

### PAPER SOAK TEST (PC FORTE)
Data/hora UTC: 2026-09-27T00:11:58Z
Baseline:
- USDT: 10000.00
- BTC: 0.00000000
- Posição: NONE
- Trades: 0
- Kill Switch: INACTIVE
- Runner Freshness: RECENT
Objetivo inicial: 72 horas
Status: Em execução independente no PC Forte (intocado).

### Dashboard Operacional
local
read only
responsive
localhost (porta 8501)

### Dashboard Lab
local
read only
responsive
localhost (porta 8502)

### Paper Runner
automated
windows task scheduler (1m)
concurrency: ignore_new
model: one-shot
soak test: active

### Real trading
disabled

### Remote access
not implemented

### API credentials
none

## Ambiente
- Windows
- Python 3.12.10
- projeto: D:\Projetos\FinBot (Notebook de desenvolvimento)
- ambiente virtual: .venv
- Git: repositório GitHub privado configurado (backup e sincronização sem CI/CD)
  - Notebook: máquina de desenvolvimento, escrita de código, commits locais durante o soak
  - PC forte: runtime 24/7 oficial executando o Soak Test
- branch: main
- remote: origin (https://github.com/ricobeliko/FinBot.git) [GitHub ignorado durante o soak]

## Arquitetura pretendida
- Python 3.12
- CCXT 4.5.84 adotado (dados públicos de mercado)
- Backtesting.py 0.6.6 adotado (simulação e estudos históricos locais)
- SQLite adotado (persistência local de paper trading e estados de risco)
- Streamlit 1.64.0 adotado (dashboards visual local 8501 e lab 8502)
- Windows Task Scheduler (orquestração periódica externa one-shot)

## Estado financeiro
- nenhuma conta autenticada
- nenhuma API key / secret
- nenhum saldo privado consultado
- nenhuma ordem real criada ou executada
- paper trading ativo com capital fictício e controle estrito de risco
- dashboards 100% read-only sem capacidade de envio de ordens
- nenhum live trade
- nenhum dinheiro real envolvido

## Decisões relevantes
- D001: Python 3.12 adotado como versão padrão.
- D002: Git exclusivamente local na fase inicial.
- D003: Arquitetura Local-first (sem cloud, sem serviços remotos).
- D004: Simplicidade acima de arquitetura sofisticada.
- D005: CCXT adotado como cliente oficial de exchange.
- D006: SQLite planejado para armazenamento local.
- D007: IA não toma decisões financeiras (regras determinísticas).
- D008: Live Trading estritamente bloqueado por padrão.
- D009: Estratégia determinística com cruzamento de médias (SMA Crossover).
- D010: Adoção de Backtesting.py para Simulação Histórica Local (AGPL-3.0+).
- D011: Arquitetura de Paper Trading com Persistência SQLite Local.
- D012: Risk Engine Determinístico e Local.
- D013: Adoção de Streamlit para Dashboard Local e Read-Only.
- D014: Automação de Ciclos Paper Trading via Windows Task Scheduler.
- D015: Telemetria Enxuta para Paper Soak Test e Rotação de Logs.
- D016: Repositório GitHub Privado para Sincronização e Backup sem CI/CD.
- D017: Arquitetura Isolada do FinBot Lab para Backtesting Paralelo e Mitigação de Overfitting.
- D018: Auditoria Metodológica e Ingestão de Dataset Histórico Ampliado (10.000 candles).
- D019: Benchmark Técnico Externo do FinBot Lab (VectorBT, Jesse, Freqtrade e Backtesting.py).

## Último checkpoint
Benchmark técnico externo (FASE 7.9A): Investigação aprofundada de VectorBT, Jesse, Freqtrade e Backtesting.py. Validação empírica de exata concordância entre VectorBT (sinais deslocados) e Backtesting.py (576 trades no benchmark SMA 5/10), identificação de otimização de fatiamento no Backtesting.py, rejeição de Jesse/Freqtrade para pilha operacional e preservação integral do Soak Test no PC Forte.

## Próxima etapa (NEXT)
FASE 7.9 — Pesquisa e screening de parâmetros em escala com walk-forward analysis e dataset ampliado.
