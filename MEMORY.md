# FinBot Memory

## Estado atual
FASE 7.9F — Features + Labels concluída no Notebook.

### Features + Labels (Contrato Matemático sem Leakage)
- Módulo `src/finbot/features.py` implementado para transformação offline de experiências em features e labels determinísticos:
  - `FeatureSet (FEATURE-SAFE)`: Mercado (price, open, high, low, close, volume), Estratégia/Indicadores (short/long windows, sma_short, sma_long, sma_distance, sma_ratio), Estado (signal, reason, position_before, risk_decision, risk_allowed) e Contexto Temporal UTC (hour 0..23, day_of_week 0..6).
  - Blindagem anti-leakage em código: `extract_features` descarta preventivamente qualquer candle posterior a `candle_timestamp`.
  - `LabelSet (OUTCOME-ONLY)`: Retornos futuros calculados rigorosamente a partir da execução em `Open[t+1]` para os horizontes de 5, 20, 50 e 100 candles (`Close[t+N]`).
  - Preservação estrita de `None` (`NULL`) para dados futuros insuficientes, sem conversão para zero.
  - Funções de construção e exportação determinística para CSV e JSON em `data/lab/results/features_labels/` (ignorado no Git).
- 152 testes automatizados (140 passando e 12 skipped no `.venv` padrão; 152 passando 100% no `.venv-research`).
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
- D022: Avaliação de Robustez e Stress Testing do WFA (Fase 7.9D).
- D023: Fundação do Experience Dataset e Blindagem Anti-Leakage (Fase 7.9E).
- D024: Especificação Matemática de Features e Labels sem Leakage (Fase 7.9F).

## Último checkpoint
Features + Labels (FASE 7.9F): Implementação de `src/finbot/features.py` estabelecendo a transformação determinística e offline de experiências em FeatureSet (decision-safe: mercado, estratégia, indicadores SMA, estado, UTC) e LabelSet (outcome-only: retornos futuros em 5, 20, 50 e 100 candles a partir de Open[t+1] até Close[t+N]). Blindagem anti-leakage comprovada matematicamente e por teste formal de mutação futura, tratamento de dados insuficientes preservando estritamente None (NULL), exportação CSV/JSON para `data/lab/results/features_labels/` e validação smoke com dataset real de 10.000 candles da Binance Spot. 152 testes passando (140 no .venv com 12 skipped isolados; 152 no .venv-research). PC Forte e Soak Test de 72h 100% intocados.

## Próxima etapa (NEXT)
FASE 7.9G — Adaptive Learning.
