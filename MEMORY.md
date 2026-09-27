# FinBot Memory

## Estado atual
FASE 7.9C — Walk-Forward Analysis (WFA) concluída no Notebook.

### FinBot Lab (Pesquisa & Otimização Offline)
- Módulo `src/finbot/lab/wfa.py` implementado com janelas deslizantes (rolling windows).
- Análise Walk-Forward executada sobre o dataset congelado de 10.000 candles de 5m (Binance Spot):
  - 6 janelas deslizantes de Train (4.000 candles / ~13,9 dias) e Test (1.000 candles / ~3,47 dias) com passo de 1.000 candles.
  - Precedência temporal rigorosa: `max(train_timestamp) < min(test_timestamp)` em 100% das janelas.
  - Seleção dos Top 20 candidatos em cada janela realizada exclusivamente no TRAIN via screening VectorBT.
  - Avaliação Out-of-Sample (OOS) realizada independentemente no FinBot Lab (`Backtesting.py`).
  - Execução real concluída em 148,79s com exportação em `data/lab/results/wfa/` (`wfa_windows.csv`, `wfa_summary.csv`, `wfa_results.json`).
  - Estrutura de dados preparada para futura ingestão em Experience Dataset (sem ML nesta fase).
- Blindagem anti-leakage e reprodutibilidade 100% comprovadas por testes unitários e de integração.
- 114 testes automatizados (104 passando e 10 skipped na suite padrão `.venv` devido ao isolamento do VectorBT de pesquisa; 14 testes de pesquisa passando 100% no `.venv-research`).
- VectorBT permanece estritamente como dependência isolada de pesquisa (`.venv-research`).

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
- ambiente virtual principal: .venv (produção/paper, 107 testes, zero dependências pesadas de pesquisa)
- ambiente virtual de pesquisa: .venv-research (isolado, contém vectorbt, numba, scipy)
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
- VectorBT Community 1.1.1 (pesquisa/screening isolado no Lab)

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
- D020: Prova do Pipeline Híbrido VectorBT (Screening Train-Only) + FinBot Lab (OOS Evaluation).
- D021: Adoção de Walk-Forward Analysis (WFA) Temporal com Screening Híbrido no FinBot Lab.

## Último checkpoint
Walk-Forward Analysis (FASE 7.9C): Implementação e validação da análise Walk-Forward com 6 janelas deslizantes (Train 4.000 / Test 1.000 / Step 1.000) sobre o dataset de 10.000 candles de 5m. Seleção 100% baseada no Train com screening VectorBT e avaliação OOS independente com Backtesting.py. Testes de anti-leakage e reprodutibilidade aprovados, exportação em CSV/JSON concluída e 114 testes da suíte passando. PC Forte e Soak Test de 72h permanecem 100% intocados.

## Próxima etapa (NEXT)
FASE 7.9D — Modelagem e Estruturação do Experience Dataset para o Futuro Learning Engine.
