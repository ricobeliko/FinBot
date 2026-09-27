# FinBot Memory

## Estado atual
FASE 7.9G — Adaptive Learning concluída no Notebook.

### Adaptive Learning (Fundação do Pipeline de Aprendizado sem Leakage)
- Módulo `src/finbot/lab/learning.py` implementado para pipeline determinístico e 100% offline:
  - *Auditoria e Suficiência*: Verificação de integridade e salvaguarda amostral objetiva (`check_sample_sufficiency`, $N \ge 50$); banco operacional de paper ($N=3$) corretamente classificado como `INSUFFICIENT_SAMPLE`.
  - *Fonte Canônica*: Dataset histórico congelado de 10.000 candles de 5m gerando 575 experiências canônicas completas a partir da estratégia SMA 5/10.
  - *Target*: `future_return_20` derivado estritamente como $(Close[t+20] - Open[t+1]) / Open[t+1]$ conforme contrato da F7.9F.
  - *Features (14)*: Exclusivamente Decision Time (`price`, `open`, `high`, `low`, `close`, `volume`, `short_window`, `long_window`, `sma_short`, `sma_long`, `sma_distance`, `sma_ratio`, `hour`, `day_of_week`). Zero campos de outcome.
  - *Split Temporal (NO SHUFFLE)*: 60% Train (345) / 20% Val (115) / 20% Test (115) com garantia $\max(Train) < \min(Val) < \min(Test)$.
  - *Pré-processamento sem Leakage*: `StandardScaler` ajustado (*fit*) exclusivamente em Train e apenas aplicado em Val e Test (suporte dual: scikit-learn no `.venv-research` e fallback puro em NumPy no `.venv`).
  - *Modelos e Avaliação*: Baseline constante de Treino vs Ridge Regression ($\alpha=1.0$).
  - *Resultado Real (10k)*: Ridge MAE Test: 0.004995 vs Baseline MAE Test: 0.003608 ($R^2 = -0.4386$). Conclusão honesta e transparente: `MODEL_DOES_NOT_BEAT_BASELINE`.
  - *Artefatos Exportados*: `data/lab/results/adaptive_learning/` (`learning_summary.csv`, `learning_results.json`, `learning_manifest.json`, `learning_coefficients.csv`).
- 170 testes automatizados (158 passando e 12 skipped no `.venv` padrão; 170 passando 100% no `.venv-research`).
- VectorBT e scikit-learn permanecem estritamente isolados no ambiente de pesquisa (`.venv-research`). Zero ML em produção.

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

## Último checkpoint
Adaptive Learning (FASE 7.9G): Implementação de `src/finbot/lab/learning.py` estabelecendo o pipeline determinístico e 100% offline de aprendizado supervisionado (Auditoria de suficiência, construção de dataset com 14 features decision-safe e target `future_return_20`, split estritamente temporal 60/20/20 sem shuffle, scaler ajustado exclusivamente em Train, baseline de média constante vs Ridge Regression regularizado, avaliação em Validação e Teste out-of-sample isolado e exportação de relatórios/manifest em `data/lab/results/adaptive_learning/`). Conclusão honesta e transparente: `MODEL_DOES_NOT_BEAT_BASELINE` (Ridge não superou o baseline no Teste out-of-sample). 170 testes passando (158 no .venv padrão com 12 skipped isolados; 170 no .venv-research). PC Forte e Soak Test de 72h 100% intocados.

## Próxima etapa (NEXT)
FASE 7.9H — Model Validation / Registry.

