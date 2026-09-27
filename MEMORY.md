# FinBot Memory

## Estado atual
FASE 7.7 — FinBot Lab concluída no Notebook (ambiente isolado de pesquisa quantitativa).

### FinBot Lab (Pesquisa & Otimização Offline)
- Arquitetura isolada em `src/finbot/lab/` para backtest paralelo e mitigação de overfitting
- Particionamento cronológico estrito (Train 60%, Validation 20%, Test 20%) sem shuffle e sem vazamento futuro
- Presets de grid (`smoke`, `standard`, `full` com trava `--confirm-full`)
- Orquestração paralela determinística via `ProcessPoolExecutor` (`workers=auto|N`)
- Dashboard analítico separado em `src/finbot/lab_dashboard.py` (porta 8502, 100% Read-Only)
- 90 testes unitários automatizados determinísticos passando
- Zero autoridade operacional: o Lab NÃO altera o bot operacional nem acessa `data/finbot_paper.sqlite3`
- *Nota Metodológica*: Resultados do dataset congelado de 500 candles são apenas validação de engenharia e não evidência suficiente de robustez da estratégia.

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

## Último checkpoint
FinBot Lab implementado e homologado no Notebook (FASE 7.7): grid search determinístico, paralelismo de CPU via Standard Library, split temporal Train/Val/Test, 90 testes passando, zero autoridade operacional e zero impacto no Paper Soak Test em andamento no PC Forte.

## Próxima etapa (NEXT)
Continuidade da observação da janela de 72 horas do Paper Soak Test no PC Forte.
