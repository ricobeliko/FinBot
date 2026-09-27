# FinBot Memory

## Estado atual
FASE 7.9I — Adaptive Paper concluída no Notebook.

### Adaptive Paper (Shadow Mode, Fail-Closed e Fallback Seguro)
- Módulo `src/finbot/adaptive.py` implementado para avaliação adaptativa sob rigorosa governança:
  - *Modos Suportados*: `off` (**Default obrigatório**), `shadow` (predição registrada sem alteração da decisão) e `adaptive` (recomendação adaptativa com fallback seguro).
  - *Registry Obrigatório e Gate de Validação*: Apenas modelos com status `VALIDATED` no `ModelRegistry` podem ser carregados (`load_validated_model`). Modelos `CANDIDATE`, `REJECTED`, `REVOKED`, inexistentes ou sem model_id configurado são bloqueados categoricamente (fail-closed).
  - *Verificação Criptográfica de Integridade*: Manifesto do modelo é validado contra dataset fingerprint, feature fingerprint e target fingerprint antes de qualquer inferência (`MODEL_INTEGRITY_FAILURE`).
  - *Soberania do Risk Engine*: A Strategy Engine (SMA) e o Risk Engine mantêm soberania total. Nenhuma predição adaptativa ignora limites de risco (`MAX_POSITION`, `KILL_SWITCH_ACTIVE`, `INSUFFICIENT_BALANCE`, `STOP_LOSS`, etc.).
  - *Shadow Mode e Detecção de Divergências*: Gravação de registros estruturados em `adaptive_predictions` no SQLite, rastreando `adaptive_recommendation` (`LONG_BIAS` / `NO_LONG_BIAS`), `final_signal == existing_signal` e `is_disagreement`.
  - *Fallback Imediato*: Qualquer erro de inferência (`NaN`, `Inf` ou exceção) dispara fail-closed e fallback transparente para a estratégia existente sem interrupção do Paper Runner.
  - *Auditoria do Modelo Real*: O único modelo real registrado (`model_b3e792893e42fd40`, Ridge Regression) permaneceu `REJECTED` e foi bloqueado com sucesso (`MODEL_REJECTED`) em testes reais.
  - *Preservação de Regressão*: Paper Trading em modo `off` mantém comportamento idêntico à linha de base.
- 210 testes automatizados (198 passando e 12 skipped no `.venv` padrão; 210 passando 100% no `.venv-research`).
- VectorBT, scikit-learn e Registry continuam restritos à pesquisa e ao ambiente de desenvolvimento. Zero live trading, zero API keys.

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
- D027: Adaptive Paper Safety Architecture (Fase 7.9I).

## Último checkpoint
Adaptive Paper (FASE 7.9I): Implementação de `src/finbot/adaptive.py` e integração controlada com o ciclo de Paper Trading (`execute_paper_cycle`), estabelecendo Shadow Mode (`MODE_SHADOW`), Adaptive Mode (`MODE_ADAPTIVE`) e modo inativo por padrão (`MODE_OFF`). Salvaguardas rigorosas implementadas: requisito mandatório de modelos formalmente com status `VALIDATED` no `ModelRegistry`; bloqueio automático (fail-closed) para modelos `CANDIDATE`, `REJECTED`, `REVOKED`, inexistentes ou sem model_id; verificação criptográfica de integridade de manifestos e fingerprints; soberania estrita do Risk Engine e da Strategy Engine sobre qualquer recomendação adaptativa; persistência dedicada em `adaptive_predictions` no SQLite e métricas acumuladas de divergência; e fallback seguro e imediato em qualquer caso de anomalia de inferência ou modelo. O modelo real existente (`model_b3e792893e42fd40`, Ridge Regression) permaneceu `REJECTED` e foi recusado categoricamente em teste real no ciclo paper, ativando fallback limpo. 210 testes automatizados passando (198 no .venv padrão com 12 skipped; 210 no .venv-research). PC Forte e Soak Test de 72h 100% intocados.

## Próxima etapa (NEXT)
FASE 8 — Live Integration.


