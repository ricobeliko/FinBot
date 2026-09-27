# FinBot Memory

## Estado atual
FASE 7.9H — Model Validation / Registry concluída no Notebook.

### Model Validation / Registry (Governança e Validação Científica sem Leakage)
- Módulo `src/finbot/lab/model_registry.py` implementado para validação formal e versionamento local:
  - *Identidade e Fingerprints Determinísticos*: `model_id` via SHA-256 do payload canônico; `dataset_fingerprint` (dados históricos), `feature_fingerprint` (ordem e versão) e `target_fingerprint` (semântica e horizonte).
  - *Manifesto Estruturado (`ModelManifest`)*: Metadados científicos completos, proveniência, ranges temporais, hiperparâmetros, pré-processamento e métricas de Treino/Validação/Teste e baseline.
  - *Estados Formais*: `CANDIDATE`, `VALIDATED`, `REJECTED`, `REVOKED`.
  - *Validation Gate*: Auditoria determinística em 7 checagens (integridade de dataset, features sem campos proibidos, target, ordenação temporal estrita $\max(Train) < \min(Val) < \min(Test)$, ausência de shuffle/leakage e superioridade out-of-sample vs baseline).
  - *Regra de Generalização*: Proibição de validar modelos com base em Treino. Modelos sem superioridade out-of-sample (Val/Test) são formalmente rejeitados.
  - *Registro do Modelo Real da F7.9G*: Ridge ($\alpha=1.0$) processado e registrado como `REJECTED` por `MODEL_DOES_NOT_BEAT_BASELINE` (MAE Val: 0.003605 vs 0.003387; MAE Test: 0.004995 vs 0.003608).
  - *Storage Append-Only*: SQLite local (`model_registry.sqlite3`) com tabela imutável `model_audit_log` e exportação para CSV e JSON em `data/lab/results/model_registry/` (ignorado no Git).
  - *CLI Local*: Suporte a comandos `list`, `show` e `validate` via `python -m finbot.lab.model_registry`.
  - *Isolamento Arquitetural*: Zero dependência ou importação nos módulos operacionais (`paper`, `risk`, `strategy`).
- 196 testes automatizados (184 passando e 12 skipped no `.venv` padrão; 196 passando 100% no `.venv-research`).
- VectorBT, scikit-learn e Registry permanecem estritamente restritos à pesquisa (`.venv-research` / `finbot.lab`). Zero ML em produção.

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
- D025: Adaptive Learning Foundation (Fase 7.9G).
- D026: Model Validation and Registry (Fase 7.9H).

## Último checkpoint
Model Validation / Registry (FASE 7.9H): Implementação de `src/finbot/lab/model_registry.py` estabelecendo a governança, integridade e versionamento local de modelos de pesquisa de forma determinística e append-only (Fingerprints de Dataset, Features e Target; model_id criptográfico; estados CANDIDATE, VALIDATED, REJECTED, REVOKED; Validation Gate com 7 auditorias de causalidade temporal, ausência de leakage e superioridade OOS vs baseline; storage SQLite local `model_registry.sqlite3` com tabela de auditoria imutável; relatórios em `data/lab/results/model_registry/` e CLI local). O modelo real da F7.9G (Ridge em 10k candles) foi registrado e classificado formalmente como `REJECTED` pelo motivo `MODEL_DOES_NOT_BEAT_BASELINE`. 196 testes passando (184 no .venv padrão com 12 skipped isolados; 196 no .venv-research). PC Forte e Soak Test de 72h 100% intocados.

## Próxima etapa (NEXT)
FASE 7.9I — Adaptive Paper.


