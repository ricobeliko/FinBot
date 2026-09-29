# FinBot — Roadmap de Desenvolvimento

Este documento descreve as etapas de evolução sequencial do FinBot. Cada fase deve estar completamente testada, validada e funcional antes de a próxima iniciar.

> **Aviso Importante**: Não implementar nenhuma fase antecipadamente. Atualmente a **FASE 7.6 (Paper Soak Test)** está em andamento (IN PROGRESS).

---

### FASE 0 — Foundation (Concluída)
- [x] Estrutura inicial de diretórios e arquivos
- [x] Documentação orientadora para agentes de IA
- [x] Configuração de repositório Git local e `.gitignore`
- [x] Ambiente virtual Python 3.12 validado
- [x] Aplicação mínima funcional sem dependências externas

---

### FASE 1 — Python Core (Concluída)
- [x] Execução central estruturada (`main.py`)
- [x] Sistema de configuração simples local (`config.py`)
- [x] Logging básico com saída em terminal e arquivo (`logging_setup.py`)

---

### FASE 2 — Market Monitor (Concluída)
- [x] Integração da biblioteca CCXT
- [x] Conexão e coleta de dados públicos de mercado (ticker, candles) via Binance Spot (`exchange.py`)
- [x] Operação estritamente em modo leitura; nenhum trade ou ordem

---

### FASE 3 — Strategy Engine (Concluída)
- [x] Mecanismo determinístico de sinais (`BUY`, `SELL`, `HOLD`)
- [x] Avaliação matemática por cruzamento de médias móveis simples (SMA 5 / SMA 10 em `strategy.py`)
- [x] Nenhuma emissão de ordens reais e trading desativado

---

### FASE 4 — Backtesting (Concluída)
- [x] Ingestão e salvamento de dataset histórico local reproduzível (`binance_BTCUSDT_5m.json`)
- [x] Simulação offline de performance e métricas via Backtesting.py (`backtest.py`)
- [x] Reutilização direta da lógica de estratégia sem duplicação (`FinBotSMAStrategy`)
- [x] Mitigação de look-ahead bias com execução simulada na abertura do candle subsequente
- [x] Comparação de desempenho com Buy & Hold e apresentação em terminal
- [x] Simulação estritamente local; nenhuma ordem enviada a exchanges

---

### FASE 5 — Paper Trading (Concluída)
- [x] Simulação de carteira com saldo fictício local e persistente via SQLite (`data/finbot_paper.sqlite3`)
- [x] Execução simulada forward testing em tempo real com capital fictício (`paper.py`)
- [x] Modelo Spot LONG exclusivo (notional técnico 100 USDT, comissão 0.10%)
- [x] Filtragem de candles em formação e deduplicação pelo timestamp do último candle fechado
- [x] Comandos CLI para execução de ciclo, consulta offline (`--status`) e reset seguro (`--reset --yes`)
- [x] Nenhuma credencial de API e nenhuma ordem real enviada à exchange

---

### FASE 6 — Risk Engine (Concluída)
- [x] Definição e aplicação de limites estritos (tamanho máximo de posição 100 USDT, perda máxima diária 50 USDT)
- [x] Mecanismo de parada de emergência (*Kill Switch*) persistente no SQLite com controle CLI (`--kill-switch on/off`)
- [x] Proteção defensiva de Stop Loss (2.0%) com prioridade máxima e motivo de saída formal (`exit_reason="STOP_LOSS"`)
- [x] Cooldown defensivo baseado em candles fechados (1 candle fechado de intervalo)
- [x] Validações de integridade contra ordens incorretas ou duplicadas (interposição obrigatória entre estratégia e broker)
- [x] Inviolabilidade de saídas (ordens SELL jamais são bloqueadas por limites defensivos)

---

### FASE 7A — Dashboard Local Visual (Concluída)
- [x] Interface visual interativa para acompanhamento local via Streamlit (`dashboard.py`)
- [x] Execução estritamente em `localhost` (127.0.0.1:8501)
- [x] Cards de saldo, patrimônio estimado, posição aberta, P/L realizado/não realizado e trades
- [x] Gráficos de evolução do P/L cumulativo baseado exclusivamente em trades reais
- [x] Painel de monitoramento do Risk Engine (Kill Switch, Daily Loss, Cooldown e bloqueios)
- [x] Módulo de métricas desacoplado (`metrics.py`) e 58 testes unitários passando
- [x] Layout responsivo com base adaptável para desktop e dispositivos móveis
- [x] Operação 100% Read-Only sem botões ou ações de execução financeira

---

### FASE 7.5 — Automated Paper Runner (Concluída)
- [x] Scripts operacionais em `scripts/` (`run_paper.ps1`, `run_dashboard.ps1`, `check_finbot.ps1`, `install_paper_task.ps1`, `remove_paper_task.ps1`)
- [x] Automação periódica a cada 1 minuto via Windows Task Scheduler
- [x] Proteção anti-sobreposição de instâncias com política `IgnoreNew` e timeout de 5 minutos
- [x] Observabilidade de ciclo persistida no SQLite (`paper_state`) e cálculo de frescor (`calculate_runner_freshness`)
- [x] Card e badge de frescor (`RECENT` vs `STALE`) no dashboard e no `--status`
- [x] Logging estruturado de cada ciclo em `logs/finbot.log`
- [x] 66 testes unitários automatizados passando

---

### FASE 7.6 — Paper Soak Test (Em Andamento / IN PROGRESS)
- **Status**: IN PROGRESS
- **Initial observation window**: 72 hours
- [x] Telemetria enxuta e atômica via `paper_state` (ciclos, sucessos, deduplicações, falhas e último erro)
- [x] Isolamento estrito de falhas de rede e recuperação automática no ciclo subsequente
- [x] Comando CLI `--soak-status` e status enriquecido
- [x] Seção de Runner Health no dashboard Streamlit
- [x] Rotação de logs com `RotatingFileHandler` (5 MB, 3 backups)
- [x] Scripts operacionais e checagem de tarefa agendada
- [x] 70 testes unitários determinísticos passando sem internet
- [ ] Observação contínua do Automated Paper Runner por 72 horas consecutivas no Windows
- [ ] Monitoramento de reconexões, reinicializações e estabilidade do SQLite (file locks)
- [ ] Avaliação de sinais, preenchimentos simulados, stop loss, cooldown e comportamento do kill switch
- [ ] Validação de estabilidade 24/7 sem vazamento de memória ou instâncias órfãs

---

### FASE 7.7 — FinBot Lab (Concluída no Notebook)
- **Status**: CONCLUÍDA
- [x] Criação do pacote `src/finbot/lab/` completamente isolado do bot operacional
- [x] Particionamento cronológico estrito (Train 60%, Validation 20%, Test 20%) sem shuffle
- [x] Gerador de grid SMA com regra `short < long` e presets (`smoke`, `standard`, `full` com trava `--confirm-full`)
- [x] Reutilização direta da função de backtest sem duplicação de lógica financeira
- [x] Orquestração paralela com `ProcessPoolExecutor` (`workers=auto|N`) e determinismo de resultados
- [x] Exportação de CSV tabular e JSON de metadados de reprodutibilidade em `data/lab/results/`
- [x] Dashboard analítico separado em `src/finbot/lab_dashboard.py` (porta 8502, 100% Read-Only)
- [x] 20 novos testes unitários determinísticos do Lab (90 testes totais no projeto)
- [x] Zero autoridade operacional: o Lab não altera nem interfere na estratégia em execução no PC Forte

---

### FASE 7.8 — Auditoria Metodológica + Dataset Histórico Maior (Concluída no Notebook)
- **Status**: CONCLUÍDA
- [x] Auditoria metodológica completa do backtest e partições Train/Val/Test (capital independente, posição zerada, sem vazamento)
- [x] Validação de warm-up interno e blindagem do ranqueamento exclusivamente pela partição de Treino
- [x] Criação de script utilitário de download paginado (`scripts/download_dataset.py`) com validação de integridade temporal e geométrica
- [x] Ingestão de dataset histórico ampliado de 10.000 candles de 5m (~34,7 dias) em `data/backtest/binance_BTCUSDT_5m_10000.json` (1.7 MB)
- [x] Preservação do dataset congelado original de 500 candles (`binance_BTCUSDT_5m.json`)
- [x] Adição de 10 testes unitários metodológicos em `tests/test_lab_methodology.py` (totalizando 100 testes no projeto)
- [x] Confirmação de execução offline sem dependência de rede durante os testes e simulações do Lab
- [x] Preservação integral do ambiente operacional e do Paper Soak Test de 72 horas no PC Forte

---

### FASE 7.9A — Benchmark Externo do FinBot Lab (Concluída no Notebook)
- **Status**: CONCLUÍDA
- [x] Investigação comparativa técnica de VectorBT Community (1.1.1), Jesse, Freqtrade Hyperopt e Backtesting.py
- [x] Ambiente de pesquisa isolado (`.venv-research`) sem contaminação do ambiente principal
- [x] Benchmark controlado de SMA 5/10 e Smoke (9 combinações) sobre 10.000 candles de 5m
- [x] Comprovação de alinhamento matemático exato entre VectorBT (com sinais deslocados) e Backtesting.py (576 trades idênticos)
- [x] Identificação de otimização de fatiamento (`data[-req:]`) para eliminar complexidade quadrática no backtest
- [x] Avaliação de dependências, compatibilidade com Windows, suporte a Docker/PostgreSQL e licenças
- [x] Definição de estratégia arquitetural: manter FinBot Lab com Backtesting.py como motor principal e avaliar VectorBT como acelerador de screening em escala
- [x] 100 testes do projeto preservados com 100% de sucesso e Soak Test de 72 horas intacto no PC Forte

---

### FASE 7.9B — Prova do Pipeline Híbrido VectorBT + FinBot Lab (Concluída no Notebook)
- **Status**: CONCLUÍDA
- [x] Prova de alinhamento semântico no TRAIN (6.000 candles): paridade exata de trades (347 trades, 48 wins, 299 losses, 13.83% win rate) entre VectorBT e Backtesting.py
- [x] Controle com Grid Smoke (9 combinações) comprovou 100% de concordância de ranqueamento e contagem de trades
- [x] Screening em escala no TRAIN com VectorBT via batching determinístico (batch_size=1.000): 1k (7,16s), 5k (45,08s), 10k (91,64s com ~2,19 GB RAM)
- [x] Seleção dos Top 20 e Top 50 candidatos baseada exclusivamente no TRAIN (zero data leakage)
- [x] Reavaliação Out-of-Sample independente no FinBot Lab (`Backtesting.py`) para Train, Validation e Test (31,0s para 20 candidatos / 60 backtests)
- [x] Teste formal e automatizado contra data leakage comprovou que alterações em Validation/Test têm ZERO efeito sobre o Top N do screening
- [x] Reprodutibilidade 100% determinística confirmada em execuções repetidas
- [x] Implementação do módulo `src/finbot/lab/hybrid.py` e bateria de 7 testes em `tests/test_lab_hybrid.py`
- [x] Preservação integral do ambiente operacional e do Paper Soak Test de 72 horas no PC Forte

---

### FASE 7.9C — Walk-Forward Analysis (WFA) (Concluída no Notebook)
- **Status**: CONCLUÍDA
- [x] Implementação do módulo `src/finbot/lab/wfa.py` com suporte a janelas deslizantes (rolling windows)
- [x] Geração determinística de 6 janelas temporais contínuas (Train 4.000 / Test 1.000 / Step 1.000) cobrindo 10.000 candles
- [x] Precedência temporal rigorosa auditada: `max(train_timestamp) < min(test_timestamp)` em todas as janelas
- [x] Seleção Top N (20 candidatos) executada exclusivamente pelo screening VectorBT no Train de cada janela
- [x] Reavaliação OOS independente no FinBot Lab (`Backtesting.py`) para cada candidato no respectivo Test
- [x] Teste de isolamento anti-leakage comprovou que alterações em Test não afetam a seleção de parâmetros do Train
- [x] Teste de reprodutibilidade determinística bit a bit aprovado
- [x] Execução real sobre os 10.000 candles concluída em 148,79s com exportação em `data/lab/results/wfa/` (`wfa_windows.csv`, `wfa_summary.csv`, `wfa_results.json`)
- [x] Adição de 7 testes unitários e de integração em `tests/test_lab_wfa.py` (totalizando 114 testes no projeto)
- [x] Preservação integral do ambiente operacional e do Paper Soak Test de 72 horas no PC Forte

---

### FASE 7.9D — Robustez e Stress Testing do WFA (Concluída no Notebook)
- **Status**: CONCLUÍDA
- [x] Implementação do módulo `src/finbot/lab/robustness.py` para testes de estresse multidimensionais
- [x] Teste de Sensibilidade a Custos: 4 níveis de fee avaliados (-25%, baseline, +25%, +50%), demonstrando decaimento linear sem perturbação no volume de trades
- [x] Teste de Vizinhança de Parâmetros (3x3): 100% das janelas temporais classificadas como PLATÔ estável (desvio padrão interno ínfimo de 0,03% a 1,00%), sem detecção de falésias
- [x] Teste de Sensibilidade ao Top N: subconjuntos de 5, 10 e 20 candidatos demonstraram invariância estatística (retorno médio entre -0,96% e -0,99%, taxa positiva estável em 17%)
- [x] Teste de Sensibilidade Temporal: avaliações com Train de 3.000, 4.000 e 5.000 candles e Test de 500 candles demonstraram consistência estrutural de assimetria negativa e dependência de W3
- [x] Análise de Concentração e Estabilidade: quantificação descritiva da distribuição OOS (média de -1,04% vs -2,30% sem a janela positiva W3) e faixas de parâmetros ([3, 4] curta / [189, 300] longa)
- [x] Persistência estruturada em `data/lab/results/robustness/` (`robustness_summary.csv`, `robustness_windows.csv`, `robustness_results.json`)
- [x] Adição de 7 testes metodológicos em `tests/test_lab_robustness.py` (totalizando 121 testes no projeto)
- [x] Preservação integral do ambiente operacional e do Paper Soak Test de 72 horas no PC Forte

---

### FASE 7.9E — Experience Dataset Foundation (Concluída no Notebook)
- **Status**: CONCLUÍDA
- [x] Criação do módulo `src/finbot/experience.py` com o modelo canônico de experiência
- [x] Separação estrita e formal entre Decision Time (`DecisionContext`) e Outcome Time (`OutcomeContext`)
- [x] Blindagem anti-leakage via `to_feature_dict()` que omite 100% dos dados de desfecho
- [x] Validação temporal matemática estrita (`outcome_at >= decision_at`) com rejeição de violações
- [x] Distinção explícita entre Decision Experience (sinais HOLD, bloqueios de risco) e Trade Experience (execuções com outcome)
- [x] Persistência local em SQLite (`experiences` table) idempotente e compatível com o banco operacional existente sem reset
- [x] Deduplicação determinística baseada na constraint `UNIQUE(source, source_id)`
- [x] Suporte à proveniência explícita (`source`: paper, backtest, wfa, research; `source_id`, `run_id`)
- [x] Exportação determinística para CSV plano e JSON estruturado em `data/lab/results/experience/` (ignorado no Git)
- [x] Tratamento rigoroso de campos ausentes: permanecem estritamente `NULL` / `None`, sem valores fabricados
- [x] Adição de 13 testes unitários metodológicos em `tests/test_experience.py` (totalizando 134 testes no projeto)
- [x] Preservação integral do ambiente operacional e do Paper Soak Test de 72 horas no PC Forte

---

### FASE 7.9F — Features + Labels (Concluída no Notebook)
- **Status**: CONCLUÍDA
- [x] Criação do módulo `src/finbot/features.py` para geração determinística e offline de features e labels
- [x] Especificação estrita da semântica temporal: `Candle[t] -> Decisão em Close[t] -> Execução em Open[t+1] -> Horizonte em Close[t+N]`
- [x] Implementação de `FeatureSet` (FEATURE-SAFE) com grupos de Mercado, Estratégia, Indicadores derivados (`sma_distance`, `sma_ratio`), Estado e Contexto temporal UTC (`hour`, `day_of_week`)
- [x] Garantia matemática de blindagem anti-leakage via filtragem prévia de histórico (`timestamp <= candle_timestamp`) e omissão de qualquer campo de resultado
- [x] Implementação de `LabelSet` (OUTCOME-ONLY) calculando retornos futuros para horizontes 5, 20, 50 e 100 candles a partir da referência `Open[t+1]`
- [x] Tratamento de dados futuros insuficientes com preservação estrita de `None` (`NULL`), sem conversão para zero ou fabricação de dados
- [x] Funções de construção de dataset consolidado e exportação determinística para CSV e JSON em `data/lab/results/features_labels/` (ignorado no Git)
- [x] Adição de 18 testes unitários e de integração em `tests/test_features_labels.py` (totalizando 152 testes no projeto)
- [x] Validação smoke aprovada contra o dataset histórico real congelado de 10.000 candles de 5m
- [x] Preservação integral do ambiente operacional e do Paper Soak Test de 72 horas no PC Forte

---

### FASE 7.9G — Adaptive Learning (Concluída no Notebook)
- **Status**: CONCLUÍDA
- [x] Criação do módulo `src/finbot/lab/learning.py` implementando o pipeline determinístico e auditado de ponta a ponta
- [x] Auditoria de dataset exploratória (`DatasetAuditResult`) e verificação objetiva de suficiência amostral (`check_sample_sufficiency`)
- [x] Definição de fonte canônica: salvaguarda para o banco de paper trading ($N=3$, status `INSUFFICIENT_SAMPLE`) e uso do histórico oficial de 10.000 candles (575 experiências reais válidas da estratégia SMA 5/10)
- [x] Definição estrita do target: `future_return_20` derivado a partir de $Open[t+1]$ e $Close[t+20]$
- [x] Seleção de 14 features exclusivas de Decision Time (`price`, `open`, `high`, `low`, `close`, `volume`, `short_window`, `long_window`, `sma_short`, `sma_long`, `sma_distance`, `sma_ratio`, `hour`, `day_of_week`) com proibição absoluta de campos de outcome
- [x] Particionamento estritamente temporal (NO SHUFFLE) em 60% Train (345) / 20% Validation (115) / 20% Test (115) com validação matemática de não-overlap ($\max(Train) < \min(Val) < \min(Test)$)
- [x] Pré-processamento sem leakage com `StandardScaler` ajustado (*fit*) exclusivamente em Train
- [x] Baseline determinístico ajustado exclusivamente em Train (`DummyRegressor` / média de Treino)
- [x] Primeiro modelo regularizado: Regressão Ridge ($\alpha=1.0$) treinado exclusivamente em Train
- [x] Isolamento estrito da partição de Teste durante o treinamento e pré-processamento
- [x] Cálculo determinístico de métricas estatísticas (MAE, RMSE, $R^2$, Acurácia Direcional, Correlação de Pearson) e diagnóstico econômico condicionado ao sinal predito
- [x] Provas anti-leakage em testes automatizados (mutação de dados futuros não altera features; altera labels)
- [x] Execução do experimento real no dataset congelado de 10.000 candles de 5m e exportação de artefatos estruturados em `data/lab/results/adaptive_learning/` (`learning_summary.csv`, `learning_results.json`, `learning_manifest.json`, `learning_coefficients.csv`)
- [x] Conclusão transparente e fundamentada: `MODEL_DOES_NOT_BEAT_BASELINE` (Ridge não superou o baseline em Val e Test; $R^2 < 0$)
- [x] Adição de 18 testes unitários e anti-leakage em `tests/test_lab_learning.py` (totalizando 170 testes no projeto)
- [x] Preservação integral do ambiente operacional e do Paper Soak Test de 72 horas no PC Forte

---

### FASE 7.9H — Model Validation / Registry (Concluída no Notebook)
- **Status**: CONCLUÍDA
- [x] Criação do módulo `src/finbot/lab/model_registry.py` com governança científica completa e local
- [x] Cálculo de fingerprints determinísticos (Dataset via SHA-256 de dados históricos, Features sensível à ordem e versão, Target com semântica e horizonte)
- [x] Identificador único determinístico (`model_id`) derivado do hash do payload canônico da identidade do modelo
- [x] Manifesto canônico estruturado (`ModelManifest`) cobrindo proveniência, splits, hiperparâmetros, pré-processamento, métricas de Treino/Validação/Teste e baseline
- [x] Implementação de estados formais de ciclo de vida: `CANDIDATE`, `VALIDATED`, `REJECTED`, `REVOKED`
- [x] Implementação do Validation Gate determinístico (`validate_model_candidate`) com 7 verificações de integridade, ausência de leakage e causalidade temporal
- [x] Regra de Generalização: Avaliação estritamente baseada em partições out-of-sample (Validação e Teste), sendo proibido validar modelos sem superioridade comprovada sobre o baseline
- [x] Registro formal do modelo real da F7.9G (Ridge em 10k candles) classificado com status `REJECTED` por `MODEL_DOES_NOT_BEAT_BASELINE`
- [x] Persistência imutável e append-only em SQLite (`data/lab/results/model_registry/model_registry.sqlite3`) com tabela `model_audit_log`
- [x] Exportação de relatórios consolidados em CSV e JSON (`registry_models.csv`, `registry_models.json`, `validation_report.json`)
- [x] Implementação de CLI local (`python -m finbot.lab.model_registry`) com comandos `list`, `show` e `validate`
- [x] Teste de isolamento arquitetural comprovando que Paper Runner, Risk e Strategy possuem zero dependências do Registry
- [x] Adição de 26 testes unitários em `tests/test_model_registry.py` (totalizando 196 testes no projeto)
- [x] Preservação integral do ambiente operacional e do Paper Soak Test de 72 horas no PC Forte

---

### FASE 7.9I — Adaptive Paper (Concluída no Notebook)
- **Status**: CONCLUÍDA
- [x] Criação do módulo `src/finbot/adaptive.py` com o motor de avaliação adaptativa e salvaguardas de execução
- [x] Configuração centralizada com `ADAPTIVE_MODE='off'` por padrão e suporte a modos `off`, `shadow` e `adaptive`
- [x] Requisito mandatório de Registry e status `VALIDATED` em `load_validated_model`
- [x] Bloqueio fail-closed para modelos `CANDIDATE`, `REJECTED`, `REVOKED`, inexistentes ou sem model_id configurado
- [x] Verificação criptográfica de integridade do manifesto e fingerprints de dataset, features e target
- [x] Implementação de Shadow Mode: predições registradas no SQLite com verificação de concordância/divergência sem alterar o sinal operacional (`final_signal == existing_signal`)
- [x] Implementação de Adaptive Mode com recomendações (`LONG_BIAS` / `NO_LONG_BIAS`) e fallback automático para a estratégia existente em caso de falha de modelo
- [x] Soberania irrestrita do Risk Engine: decisões adaptativas submetidas integralmente a todas as travas de risco (posição máxima, saldo, stop loss, cooldown, kill switch)
- [x] Persistência em tabela SQLite dedicada `adaptive_predictions` com rastreabilidade completa e sem contaminação do dataset de experiências
- [x] Tabela de métricas acumuladas de predição via `storage.get_adaptive_metrics()`
- [x] Teste de regressão garantindo que o Paper Trading em `ADAPTIVE_MODE='off'` é 100% equivalente ao comportamento anterior
- [x] Experimento real com o modelo Ridge da F7.9G (`model_b3e792893e42fd40`): bloqueio comprovado com `MODEL_REJECTED` e ativação segura do fallback
- [x] Adição de 14 testes unitários e de integração em `tests/test_adaptive.py` (totalizando 210 testes no projeto)
- [x] Preservação integral do ambiente operacional e do Paper Soak Test de 72 horas no PC Forte

---

### FASE 7B — Dashboard Mobile-Friendly / Refinamento
- Testes e refinamento visual direcionados para telas pequenas (smartphones e tablets)
- Melhorias ergonômicas de navegação e densidade de informação
- Auto-refresh suave configurável sem sobrecarga do processo

---

### FASE 7C — Acesso Remoto Seguro Read-Only
- Avaliação de arquitetura para acesso remoto restrito (ex: túnel SSH / PWA / VPN local)
- Mecanismo de autenticação e proteção de perímetro (sem expor credenciais à internet)
- Preservação do princípio Read-Only estrito

---

### FASE 8 — Integração com Conta Real

#### FASE 8.1 — Binance Private Integration Foundation (Concluída no Notebook)
- **Status**: CONCLUÍDA
- [x] Criação do módulo isolado `src/finbot/private_exchange.py` encapsulando exclusivamente operações privadas Binance Spot
- [x] Configuração segura centralizada em `src/finbot/config.py`: `TRADING_MODE` (default obrigatório `paper`), `BINANCE_API_KEY`, `BINANCE_API_SECRET`
- [x] Proteção ativa de credenciais: mascaramento com `repr=False`, sanitização em logs e exceções (`sanitize_secret_text`), proibição de persistência em SQLite, CSV ou datasets
- [x] Separação estrita Paper / Live: modo `paper` bloqueado de invocar endpoints privados; modo `live` restrito estritamente a operações READ-ONLY nesta fase
- [x] Métodos de consulta normalizados: `get_account_status()`, `get_balances()`, `get_balance(asset)`, `get_account_snapshot()` com modelo `AccountSnapshot`
- [x] Informação vs Autorização: `can_trade` tratado estritamente como dado descritivo da Binance, sem capacidade de autorizar ordens no FinBot
- [x] Bloqueio arquitetural de ordens reais: métodos de envio/cancelamento de ordens (`create_order`, `cancel_order`) levantam `LiveTradingBlockedError`
- [x] Tratamento de erros fail-closed: hierarquia dedicada (`CredentialsMissingError`, `AuthenticationError`, `NetworkError`, `RateLimitError`, `InvalidConfigurationError`)
- [x] Adição de 22 testes unitários e de segurança em `tests/test_private_exchange.py` (totalizando 232 testes no projeto)
- [x] Teste privado manual em ambiente sem credenciais registrado como `NOT_RUN_NO_CREDENTIALS` sem invenção de dados
- [x] Preservação integral do ambiente operacional e do Paper Soak Test de 72 horas no PC Forte

#### FASE 8.2A — Secure Windows Credential Storage (Concluída no Notebook)
- **Status**: CONCLUÍDA
- [x] Criação do módulo `src/finbot/credentials.py` com interface `CredentialProvider` e dataclass `BinanceCredentials`
- [x] Implementação nativa `WindowsCredentialProvider` usando Windows Credential Manager via `ctypes` e `Advapi32.dll` (target `FinBot/Binance/Production`)
- [x] Implementação de `FakeCredentialProvider` para isolamento de testes unitários sem dependência do cofre do sistema
- [x] Eliminação de credenciais privadas em variáveis de ambiente (`BINANCE_API_KEY`, `BINANCE_API_SECRET` removidas de `get_config()`) e arquivos `.env`
- [x] Proteção ativa em memória: `repr=False`, mascaramento customizado `BinanceCredentials(api_key=[PROTECTED], api_secret=[PROTECTED])`
- [x] Higienização estrita de logs e exceções (`sanitize_secret_text`), proibição de persistência em arquivos de dados ou SQLite
- [x] CLI administrativa segura (`python -m finbot.credentials` com comandos `setup`, `status`, `remove` e senha oculta via `getpass`)
- [x] Adaptação de `BinancePrivateExchange` para obter credenciais exclusivamente via `CredentialProvider`
- [x] Preservação do modo Paper: `TRADING_MODE=paper` permanece desacoplado e não consulta o Windows Credential Manager
- [x] Adição de 18 testes unitários de segurança em `tests/test_credentials.py` (totalizando 250 testes no projeto)
- [x] Preservação integral do ambiente operacional e do Paper Soak Test de 72 horas no PC Forte

#### FASE 8.2B — GUI Local Segura para Cadastro das Credenciais Binance (Concluída no Notebook)
- **Status**: CONCLUÍDA
- [x] Criação de interface gráfica local nativa via Tkinter (`src/finbot/credentials_gui.py`) para cadastro e substituição segura de credenciais Binance
- [x] Ocultação visual do API Secret com máscara padrão (`show="*"`) e controle opcional de alternância ("Mostrar API Secret")
- [x] Validação preventiva contra colagem truncada (prevenção contra `SECRET_LEN=2` ocorrido no terminal) e quebras de linha
- [x] Armazenamento exclusivo no Windows Credential Manager via `WindowsCredentialProvider` (target `FinBot/Binance/Production`)
- [x] Isolamento estrito de rede: salvar credenciais não realiza chamadas à Binance (cadastro e teste permanecem separados)
- [x] Proibição total de persistência em arquivos (`.env`, `.json`, `.yaml`, SQLite, CSV) e de segredos em logs, terminal ou exceções
- [x] Limpeza imediata dos campos de entrada em memória após o salvamento bem-sucedido
- [x] CLI de invocação dedicada (`python -m finbot.credentials_gui`) e integração da ação `gui` na CLI existente (`python -m finbot.credentials gui`)
- [x] Adição de 16 testes unitários em `tests/test_credentials_gui.py` (totalizando 267 testes no projeto)
- [x] Preservação integral do ambiente operacional e do Paper Soak Test de 72 horas no PC Forte

#### FASE 8.2C — Binance Private Read-Only Validation (Concluída no PC Forte)
- **Status**: CONCLUÍDA
- [x] Homologação operacional realizada e validada no ambiente de execução oficial do PC Forte (`C:\Projetos\FinBot`)
- [x] Status do Windows Credential Manager: `PRESENT` sob target canônico `FinBot/Binance/Production`
- [x] Validação estrutural de credenciais: API Key (64 caracteres), API Secret (64 caracteres), zero espaços nas extremidades
- [x] Diagnóstico e resolução da causa raiz do erro Binance -1022 (truncamento na entrada do terminal resolvido pela GUI da Fase 8.2B)
- [x] Autenticação privada real validada via `BinancePrivateExchange.get_account_status()`: `PASS`
- [x] Consulta privada de saldos da conta via `BinancePrivateExchange.get_balances()`: `PASS`
- [x] API com permissões estritas: apenas leitura (Read-Only), restrição de IP configurada para o PC Forte, trading desabilitado na API, saídas desabilitadas (zero withdrawals) e transferências desabilitadas (zero transfers)
- [x] Bloqueio arquitetural de ordens reais 100% mantido: zero ordens criadas, zero ordens canceladas, nenhum endpoint de trading invocado (`create_order` e `cancel_order` bloqueados com `LiveTradingBlockedError`)
- [x] Preservação integral do ambiente operacional e do Paper Soak Test de 72 horas no PC Forte

#### FASE 8.3 — Live Execution Safety Foundation (Concluída no Notebook)
- **Status**: CONCLUÍDA
- [x] Criação do módulo `src/finbot/live_safety.py` com fundação defensiva preliminar antes de qualquer execução live
- [x] Princípio de Separação Estrita: `SIGNAL -> ORDER INTENT -> RISK ENGINE -> MARKET FILTER GUARD -> STATE RECONCILIATION -> LIVE SAFETY GATE -> APPROVED INTENT`
- [x] Regra Mandatória: `APPROVED INTENT != EXECUTED ORDER` (execução real inexistente nesta fase)
- [x] Estrutura imutável `OrderIntent` (frozen dataclass) com validação estrutural no construtor (rejeição de strings vazias, valores <= 0, NaN, Inf)
- [x] Implementação do `MarketFilterGuard` consumindo metadados normalizados do CCXT (`limits` e `precision`) e raw `info.filters` com fallback auditado
- [x] Funções puras em `Decimal`: `sanitize_amount`, `sanitize_price`, `validate_notional` sem hardcoding de valores da Binance
- [x] Política de truncamento estrito: ordens truncadas para passos inteiros válidos (`stepSize`, `tickSize`), sendo categoricamente proibido inflar quantidades para atingir limites mínimos
- [x] Rejeição fail-closed para ordens abaixo do lote mínimo (`BELOW_MIN_AMOUNT`) ou notional mínimo (`BELOW_MIN_NOTIONAL`)
- [x] Implementação de `StateReconciler` e `AccountStateSnapshot`: reconciliação passiva exigindo saldo livre de quote para BUY e base para SELL (sem mutações ou vendas automáticas)
- [x] Soberania irrestrita do Risk Engine: rejeições do Risk Engine são absorvidas de forma final pelo `LiveSafetyGate` sem override ou bypass
- [x] Hard Live Limit operacional (`live_max_order_notional`, default 100 USDT) via `src/finbot/config.py` com rejeição imediata se excedido
- [x] Autorização explícita de live trading (`live_trading_acknowledged`, default `False`) requerida para elegibilidade de intenção
- [x] Investigação formal de `AccountStatus` (`can_trade`, `can_withdraw`): demonstrado que refletem KYC/AML da conta mestra, e NÃO permissões da API Key; proibido utilizá-los como gate de autorização
- [x] Auditoria local append-only em SQLite (`live_safety_decisions` via `LiveSafetyAuditStorage`) registrando apenas dados operacionais sem credenciais
- [x] Inviolabilidade de `create_order` e `cancel_order`: preservados com `LiveTradingBlockedError` em `BinancePrivateExchange`
- [x] Teste sentinela `test_phase_8_3_cannot_submit_real_orders` provando a impossibilidade de envio de ordens reais
- [x] Adição de 22 testes unitários e de integração em `tests/test_live_safety.py` (totalizando 289 testes no projeto)
- [x] Preservação integral do ambiente operacional e do Paper Soak Test de 72 horas no PC Forte

#### FASE 8.4A — Live Execution Engine / Dry-Run (Concluída no Notebook)
- **Status**: CONCLUÍDA
- [x] Criação do módulo `src/finbot/execution.py` com o motor de execução em modo Dry-Run
- [x] Princípio Soberano: `APPROVED ORDER INTENT != REAL ORDER` e `DRY_RUN != PAPER TRADING`
- [x] Implementação de `DryRunExecutionEngine` consumindo exclusivamente `ApprovedOrderIntent` (fail-closed para intenções não aprovadas)
- [x] Modos de execução com enum `ExecutionMode`: obrigatoriedade de `DRY_RUN` e bloqueio estrito de `LIVE` via `LiveExecutionBlockedError`
- [x] Estrutura imutável `DryRunOrderResult` com status explícitos (`SIMULATED_ACCEPTED`, `DUPLICATE_INTENT`) e proibição de status `FILLED`
- [x] Geração determinística de `clientOrderId` (`generate_client_order_id`) compatível com o limite de 36 caracteres e formato da Binance Spot (`finbot_<sha256[:28]>`)
- [x] Mecanismo de idempotência em SQLite (`DryRunStorage` na tabela `dry_run_orders`), garantindo que intenções repetidas não gerem segunda execução
- [x] Persistência auditável entre reinicializações do processo, sem gravação de credenciais, chaves ou senhas
- [x] Função pura `build_order_payload` construindo o payload canônico para o adapter da exchange com preservação rigorosa de precisão
- [x] Orquestrador de pipeline `run_dry_run_pipeline`: se o `LiveSafetyGate` rejeitar, o `DryRunExecutionEngine` nunca é invocado
- [x] Inviolabilidade de trading real: `create_order` e `cancel_order` permanecem levantando `LiveTradingBlockedError` na `BinancePrivateExchange`
- [x] Teste sentinela `test_phase_8_4a_has_zero_live_order_capability` aprovado
- [x] Adição de 25 testes unitários e de integração em `tests/test_execution.py` (totalizando 314 testes no projeto)
- [x] Preservação integral do ambiente operacional e do Paper Soak Test de 72 horas no PC Forte

#### FASE 8.4B — Guarded Live Order Executor Foundation (Concluída no Notebook)
- **Status**: CONCLUÍDA
- [x] Criação do módulo `src/finbot/live_executor.py` com a arquitetura defensiva do executor live
- [x] Entrada exclusiva para `ApprovedOrderIntent` com rejeição fail-closed de `OrderIntent` cru, `RejectedOrderIntent` ou tipos inválidos (`InvalidExecutionIntentError`)
- [x] Triple Live Arming com três travas independentes e cumulativas: `trading_mode == 'live'`, `live_trading_acknowledged == True` e `live_execution_enabled == True` (default `False`, erro `LiveExecutionArmingError`)
- [x] Micro-Order Cap com teto dedicado de homologação `live_micro_order_max_notional` (default conservador: 15.0 USDT) com rejeição imediata (`MicroOrderCapExceededError`) e proibição de redução automática da ordem
- [x] Protocolo abstrato `ExchangeOrderAdapter` desacoplando o motor da rede e exigindo injeção explícita de dependência no construtor de `GuardedLiveExecutionEngine` (sem criação automática de `BinancePrivateExchange`)
- [x] Implementação de `FakeExchangeOrderAdapter` para testes unitários isolados com simulação de preenchimentos, recusas e timeouts
- [x] Implementação de `BinanceOrderAdapter` com barreira final de segurança: bloqueio obrigatório por `real_order_submission_enabled == False` (default) levantando `RealOrderSubmissionBlockedError` antes de qualquer chamada ao CCXT
- [x] Inviolabilidade contínua de `BinancePrivateExchange.create_order()` e `cancel_order()` bloqueados com `LiveTradingBlockedError`
- [x] Teste sentinela `test_phase_8_4b_cannot_reach_real_binance_order_endpoint` aprovado (comprova que mesmo com todas as flags de LIVE ativadas, a barreira final impede o envio)
- [x] Idempotência com persistência mandatória de `PENDING_SUBMISSION` com `correlation_id` e `client_order_id` antes do envio, prevenindo submissões duplicadas em reinicializações ou retries
- [x] Máquina de estados completa de ciclo de vida: `PREPARED`, `PENDING_SUBMISSION`, `SUBMITTED`, `ACKNOWLEDGED`, `PARTIALLY_FILLED`, `FILLED`, `CANCEL_PENDING`, `CANCELED`, `REJECTED`, `UNKNOWN`
- [x] Regra Mandatória de Falha Ambígua: `UNKNOWN != FAILED` e `TIMEOUT != SAFE TO RETRY` (timeouts de rede resultam estritamente em `UNKNOWN`, proibindo retry automático e exigindo reconciliação)
- [x] Implementação de `reconcile_order(client_order_id)` para consulta do estado da ordem na exchange via `clientOrderId`
- [x] Fluxo de cancelamento seguro `cancel_order(client_order_id)`: exige ordem conhecida, status cancelável (`SUBMITTED`, `ACKNOWLEDGED`, `PARTIALLY_FILLED`), bloqueia cancelamento de ordens `FILLED` (`OrderNotCancelableError`) e exige reconciliação prévia se `UNKNOWN` (`AmbiguousExecutionError`)
- [x] Auditoria local append-only em SQLite (`LiveOrderStorage`) nas tabelas `live_orders` e `live_order_lifecycle` com rastreamento completo de transições de estado e motivo, sem expor chaves ou credenciais
- [x] Adição de 22 testes unitários e de integração em `tests/test_live_executor.py` (totalizando 336 testes no projeto)
- [x] Preservação integral do ambiente operacional e do Paper Soak Test de 72 horas no PC Forte

#### FASE 8.4C — Assisted Binance Micro-Order Validation

##### FASE 8.4C1A — Implementação e Testes do Comando Operacional de Pre-Flight (Concluída no Notebook)
- **Status**: CONCLUÍDA
- [x] Criação do módulo `src/finbot/preflight.py` com o comando operacional `python -m finbot.preflight`
- [x] Estrutura estritamente read-only e fail-closed: impossibilidade estrutural de submeter ou cancelar ordens reais
- [x] Validação de credenciais via `WindowsCredentialProvider` sem expor API Key, Secret ou comprimentos de chave
- [x] Validação de autenticação privada (`BINANCE_PRIVATE_AUTH = PASS`) e leitura de saldos (`PRIVATE_BALANCE_READ = PASS`) sem exibir valores patrimoniais no terminal ou logs
- [x] Extração e validação pública de metadados e filtros de mercado de `BTC/USDT` via CCXT (`symbol`, `min_amount`, `step_size`, `price_tick`, `min_notional`)
- [x] Validação dos filtros de mercado através do `MarketFilterGuard`
- [x] Cálculo dinâmico de micro-ordem candidata segura (`calculate_micro_order_candidate`) respeitando `minNotional` e `live_micro_order_max_notional` (15.0 USDT) com margem de tolerância (~15%)
- [x] Verificação passiva de fundos disponíveis para a candidata (`FUNDS_AVAILABLE_FOR_CANDIDATE = YES/NO`) sem exibir saldo
- [x] Execução simulada da candidata no pipeline defensivo completo em modo `DRY_RUN` (`SIMULATED_ACCEPTED`)
- [x] Verificação local e hermética da barreira final (`real_order_submission_enabled == False`)
- [x] Verificação estrutural das barreiras de `create_order` e `cancel_order` (`LiveTradingBlockedError`)
- [x] Teste sentinela `test_preflight_cannot_submit_or_cancel_real_orders` aprovado (zero ordens enviadas, zero chamadas de ordem para a rede)
- [x] Adição de 14 testes unitários e de segurança em `tests/test_preflight.py` (totalizando 350 testes no projeto)
- [x] Procedimento operacional documentado na Seção 14 de `RUNBOOK.md`
- [x] Preservação integral do ambiente operacional e do Paper Soak Test de 72 horas no PC Forte

##### FASE 8.4C1B — Execução Read-Only e Verificação de Barreiras no PC Forte (Concluída)
- **Status**: CONCLUÍDA
- [x] Execução do comando `python -m finbot.preflight` no ambiente de produção (PC Forte) com credenciais oficiais
- [x] Validação ao vivo da autenticação e consulta de saldos (read-only)
- [x] Confirmação dos filtros reais atuais de mercado de `BTC/USDT`
- [x] Cálculo e exibição da micro-ordem candidata em tempo real
- [x] Obtenção do resultado mandatório `READY_FOR_8_4C2 = YES`
- [x] Inviolabilidade operacional confirmada: zero ordens reais enviadas

##### FASE 8.4C2A — Spot Testnet Foundation & Production Isolation (Concluída no Notebook)
- **Status**: CONCLUÍDA
- [x] Separação explícita de ambientes via `BinanceEnvironment` (`PRODUCTION` vs `SPOT_TESTNET`)
- [x] Armazenamento independente de credenciais no Windows Credential Manager: target `FinBot/Binance/SpotTestnet` vs `FinBot/Binance/Production`
- [x] Adaptação de CLI (`credentials.py`) e GUI (`credentials_gui.py`) com alternância explícita e visual de ambiente
- [x] Implementação de `BinanceSpotTestnetOrderAdapter` para `https://testnet.binance.vision` com ativação imediata de CCXT sandbox mode (`set_sandbox_mode(True)`)
- [x] Sentry defensivo fail-closed: verificação obrigatória de que endpoint contém `testnet.binance.vision` e jamais `api.binance.com` antes de qualquer WRITE
- [x] Armamento independente da Testnet: `testnet_execution_enabled == True` (default `False`); flags de produção não liberam testnet e flags de testnet não liberam produção
- [x] Reutilização integral do pipeline de segurança (`Risk Engine -> MarketFilterGuard -> LiveSafetyGate -> ApprovedOrderIntent -> GuardedLiveExecutionEngine -> BinanceSpotTestnetOrderAdapter`)
- [x] Implementação do comando operacional read-only `python -m finbot.testnet_preflight` emitindo veredito `READY_FOR_TESTNET_ORDER = YES/NO`
- [x] Adição de 22 testes unitários e de isolamento em `tests/test_testnet.py` (totalizando 372 testes no projeto)
- [x] Zero ordens reais de produção enviadas (`PRODUCTION_ORDERS_SENT = 0`), zero ordens de testnet enviadas durante testes (`TESTNET_ORDERS_SENT = 0`)
- [x] Preservação integral do ambiente operacional e do Paper Soak Test de 72 horas no PC Forte

##### FASE 8.4C2B — Spot Testnet Operational Validation (Pendente)
- [ ] Cadastro das credenciais da Testnet no Windows Credential Manager via GUI ou CLI segura
- [ ] Execução operacional do comando read-only: `python -m finbot.testnet_preflight`
- [ ] Validação de autenticação, saldo fictício e metadados na Spot Testnet real
- [ ] Obtenção do veredito `READY_FOR_TESTNET_ORDER = YES`
- [ ] Submissão assistida de micro-ordem de teste na Spot Testnet
- [ ] Validação de ciclo de vida (ACK, Fill, Reconciliação, Cancelamento) sem risco financeiro

##### FASE 8.4C3 — Assisted Production Micro-Order Validation (Pendente)
- Primeira micro-operação real controlada e assistida na Binance Spot com o operador:
  - Liberação assistida e supervisionada das travas de submissão no PC Forte exclusivamente para uma única micro-ordem
  - Validação do fluxo completo: Submissão -> ACK -> Fill -> Reconciliação de saldo real
  - Validação assistida do fluxo de cancelamento de micro-ordem limite longe do book
  - Re-armamento imediato de todas as travas e preservação contínua do Paper Soak Test no PC Forte

---

### FASE 9 — Estabilidade 24/7
- Tratamento avançado de desconexões de rede e falhas de socket/HTTP
- Mecanismos de reinício automático e recuperação de estado consistente
- Alarmes e logs detalhados de anomalias operacionais

---

### FASE 10 — Instalação no PC Definitivo
- Preparação para migração ao PC definitivo de execução (Windows)
- Scripts de instalação e provisionamento do ambiente
- Scripts de inicialização automática e monitoramento de processo em segundo plano
