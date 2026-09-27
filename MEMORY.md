# FinBot Memory

## Estado atual
FASE 7.9B — Prova do Pipeline Híbrido VectorBT + FinBot Lab concluída no Notebook.

### FinBot Lab (Pesquisa & Otimização Offline)
- Arquitetura híbrida comprovada em `src/finbot/lab/hybrid.py`:
  - Estágio 1: Screening ultrarrápido com VectorBT Community via Numba/NumPy em lotes de 1.000 combinações estritamente sobre a partição de TRAIN (6.000 candles).
  - Estágio 2: Reavaliação OOS rigorosa e independente dos Top N candidatos no FinBot Lab (`Backtesting.py`) para Train, Validation e Test.
- Alinhamento semântico auditado e comprovado: sinais no Close[t], deslocados via shift(1), executados no Open[t+1] (347 trades idênticos na SMA 5/10).
- Ranqueamento smoke (9 combinações) 100% idêntico entre VectorBT e FinBot Lab.
- Screening em escala: 1k (7,16s), 5k (45,08s), 10k (91,64s com ~2,19 GB de pico de RAM com batching).
- Blindagem anti-leakage comprovada formalmente: mutações arbitrárias em Validation e Test produzem zero alteração no Top N gerado pelo screening de Train.
- Reprodutibilidade 100% determinística confirmada.
- 107 testes automatizados (101 passando e 6 skipped na suite padrão `.venv` devido à ausência do VectorBT de pesquisa; 7 testes do módulo híbrido passando 100% no ambiente `.venv-research`).
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

## Último checkpoint
Prova do pipeline híbrido (FASE 7.9B): Comprovação experimental completa do pipeline híbrido de dois estágios. VectorBT realiza screening de até 10.000 combinações em ~91s exclusivamente sobre o Train (6.000 candles), seleção de Top N sem nenhum vazamento para Validation/Test, reavaliação out-of-sample independente via FinBot Lab / Backtesting.py, paridade exata de trades e teste formal anti-leakage 100% aprovado. PC Forte e Soak Test permanecem intocados.

## Próxima etapa (NEXT)
FASE 7.9C — Walk-Forward Analysis e Expansão de Espaço Amostral no FinBot Lab.
