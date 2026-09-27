# FinBot Memory

## Estado atual
FASE 8.2A — Secure Windows Credential Storage concluída no Notebook.

### Secure Windows Credential Storage (FASE 8.2A)
- Módulo `src/finbot/credentials.py` implementado com arquitetura de provedores de credenciais e proteção estrita contra vazamento:
  - *Armazenamento Oficial de Produção*: **Windows Credential Manager** via `WindowsCredentialProvider`, utilizando a API nativa do Windows (`Advapi32.dll` via `ctypes`: `CredReadW`, `CredWriteW`, `CredDeleteW`, `CredFree`) sob o target canônico `FinBot/Binance/Production`.
  - *Proibição Absoluta de Arquivos e Variáveis de Ambiente*: Credenciais de produção NÃO são aceitas nem lidas de `.env`, `.json`, `.yaml`, `.toml`, SQLite, CSV, logs ou variáveis de ambiente (`BINANCE_API_KEY`/`BINANCE_API_SECRET`).
  - *Estrutura Blindada em Memória*: Dataclass `BinanceCredentials` implementa `repr=False` e mascaramento customizado `__repr__` e `__str__` (`[PROTECTED]`), impedindo exposição em logs, dumps, terminal ou inspeções de objetos.
  - *Provedor para Testes Automatizados*: `FakeCredentialProvider` em memória permite testes unitários determinísticos, sem tocar no Credential Manager do sistema nem depender da Binance.
  - *Princípio Fail-Closed*: Se as credenciais estiverem ausentes no Windows Credential Manager, lança `CredentialsMissingError` imediatamente, sem chamada de rede, sem fallback para paper e sem tentativa de ordens.
  - *CLI Administrativa Segura*: Comandos `python -m finbot.credentials` (`setup` com senha oculta via `getpass`, `status` sem expor segredos, `remove` com confirmação explícita).
  - *Preservação do Modo Paper*: O modo `paper` (`TRADING_MODE=paper`) permanece 100% desacoplado e não consulta o Windows Credential Manager.
- 250 testes automatizados (238 passando e 12 skipped no `.venv` padrão; 250 passando 100% no `.venv-research`).

### Binance Private Integration Foundation (Read-Only Live Boundary)
- Módulo isolado `src/finbot/private_exchange.py` adaptado para obter credenciais exclusivamente via `CredentialProvider`.
- *Trading Mode*: `TRADING_MODE` centralizado em `src/finbot/config.py` com valor default mandatório `paper`. Modo `paper` não invoca nem instancia endpoints privados.
- *Live Read-Only Estrito*: Modo `live` restrito a consultas autenticadas de conta e saldo (`get_account_status`, `get_balances`, `get_balance`, `get_account_snapshot`).
- *can_trade Informativo*: O flag `can_trade` do snapshot de conta é tratado estritamente como dado descritivo retornado pela Binance; não concede permissão nem autoriza ordens no FinBot.
- *Bloqueio Arquitetural de Ordens*: Métodos de envio e cancelamento de ordens (`create_order`, `cancel_order`) levantam expressamente `LiveTradingBlockedError`. Não há caminho executável para ordens reais nesta fase.
- *Teste Privado*: `PRIVATE_READ_TEST = NOT_RUN_NO_CREDENTIALS` (chaves reais ainda não cadastradas).

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
- VectorBT, scikit-learn e Registry continuam restritos à pesquisa e ao ambiente de desenvolvimento. Zero ordens reais.

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
- Armazenamento oficial de produção no PC Forte: Windows Credential Manager (target `FinBot/Binance/Production`).
- Variáveis de ambiente (`BINANCE_API_KEY`/`BINANCE_API_SECRET`) e arquivos `.env` proibidos e desabilitados em produção.
- Credenciais ausentes no ambiente de desenvolvimento local (`PRIVATE_READ_TEST = NOT_RUN_NO_CREDENTIALS`).

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
- D028: Binance Private Integration Foundation and Read-Only Live Boundary (Fase 8.1).
- D029: Windows Credential Manager for Binance Secrets (Fase 8.2A).

## Último checkpoint
FASE 8.2A — Secure Windows Credential Storage: Implementação do módulo `src/finbot/credentials.py` com `WindowsCredentialProvider` (nativo via `ctypes` e `Advapi32.dll`), `FakeCredentialProvider` para testes e CLI administrativa segura (`setup`, `status`, `remove`). `BinancePrivateExchange` adaptado para consumir credenciais exclusivamente via `CredentialProvider` com semântica fail-closed. Credenciais removidas de `get_config()`, `.env` e variáveis de ambiente. Segredos mascarados via `BinanceCredentials(repr=False)` e higienização contínua de logs. 18 novos testes unitários adicionados em `tests/test_credentials.py` e suíte de private exchange adaptada (totalizando 250 testes automatizados: 238 passando e 12 skipped no ambiente padrão; 250 passando 100% no ambiente research). Nenhuma chave real cadastrada nesta fase. Paper Soak Test de 72h no PC Forte 100% preservado e intocado.

## Próxima etapa (NEXT)
FASE 8.2B — Cadastro de Credenciais Reais e Teste Read-Only Live (após término do Soak Test e validação operacional).
