# FinBot Memory

## Estado atual
FASE 7.9E — Experience Dataset Foundation concluída no Notebook.

### Experience Dataset (Memória Estruturada de Experiências)
- Módulo canônico `src/finbot/experience.py` implementado com separação formal entre Decision Time e Outcome Time:
  - `DecisionContext (FEATURE-SAFE)`: captura exclusivamente variáveis conhecidas em `decision_at` (OHLCV fechado, preço, sinal, parâmetros, avaliação de risco, execução).
  - `OutcomeContext (OUTCOME-ONLY)`: captura variáveis descobertas pós-decisão (`outcome_at`, `exit_price`, `realized_pnl`, `realized_return`, `fees`, `mfe`, `mae`, `trade_duration`, horizontes futuros `future_return_*`, `outcome`).
  - Blindagem anti-leakage garantida em código via `to_feature_dict()` e validação temporal estrita (`outcome_at >= decision_at`).
  - Suporte explícito a Decision Experience (sinais HOLD, bloqueios pelo Risk Engine) e Trade Experience (operações executadas).
  - Persistência atômica no SQLite local (`experiences` table) com deduplicação via `UNIQUE(source, source_id)`.
  - Exportação determinística para CSV e JSON em `data/lab/results/experience/`.
  - Tratamento de campos desconhecidos como `NULL` / `None`, sem valores fabricados ou aproximações com 0.
- 134 testes automatizados (122 passando e 12 skipped no `.venv` padrão; 134 passando 100% no `.venv-research`).
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

## Último checkpoint
Fundação do Experience Dataset (FASE 7.9E): Implementação de `src/finbot/experience.py` estabelecendo a memória canônica do FinBot. Separação formal e matemática entre Decision Time (feature-safe) e Outcome Time (outcome-only), validação de precedência temporal estrita anti-leakage (`outcome_at >= decision_at`), suporte a Decision Experience (HOLD, bloqueios de risco) e Trade Experience, persistência SQLite com deduplicação em `UNIQUE(source, source_id)` compatível com banco existente, e exportação determinística para CSV/JSON em `data/lab/results/experience/`. 134 testes passando (122 no .venv com 12 skipped isolados; 134 no .venv-research). PC Forte e Soak Test de 72h 100% intocados.

## Próxima etapa (NEXT)
FASE 7.9F — Features + Labels.
