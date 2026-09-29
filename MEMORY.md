# FinBot Memory

## Estado atual
FASE 8.4C2A — Integração Binance Spot Testnet e Isolamento de Produção CONCLUÍDA.
FASE 8.4C2B — Validação Operacional da Binance Spot Testnet CONCLUÍDA.
FASE 8.4C2C — Validação do Ciclo de Vida de Execução na Binance Spot Testnet CONCLUÍDA OPERACIONALMENTE.
FASE 8.4C2D — Binance Spot Testnet Soak (S1) CONCLUÍDA NO NOTEBOOK.
FASE 8.4C2E — Testnet Soak Hardening & PC Forte Deployment Readiness CONCLUÍDA NO NOTEBOOK.

### Testnet Soak Hardening & PC Forte Deployment Readiness (FASE 8.4C2E)
- *Observabilidade Dinâmica de Status & Heartbeat*:
  - Implementação de `determine_runner_status(storage, circuit_breaker, heartbeat_timeout_seconds=180.0)`.
  - Estados dinâmicos: `READY/IDLE`, `RUNNING`, `STOPPED`, `CIRCUIT_BREAKER_TRIPPED`.
- *Encerramento Gracioso (Graceful Shutdown)*:
  - Captura segura de `KeyboardInterrupt` / `Ctrl+C` em `run_testnet_soak_continuous`.
  - Persistência de `runner_status = "STOPPED"` e `shutdown_at` no SQLite.
  - Fechamento limpo de conexões e preservação estrita de posições e ordens UNKNOWN para reconciliação futura.
- *Restart com Reconciliação Pré-Ciclo Mandatória*:
  - Função `reconcile_pre_cycle_state` executada ANTES da tomada de decisão de Strategy / Risk Engine.
  - Reconcilia todas as ordens não-terminais com a exchange.
  - Reconstrói a posição local a partir do histórico auditado de trades e valida contra saldos da exchange.
  - Disparo imediato de Circuit Breaker (`stop_new_orders = True`) sob ordens UNKNOWN pendentes ou divergência de saldo.
- *Contabilização Realista de Taxas (Fees)*:
  - Segregação contábil explícita entre `EXCHANGE_REPORTED_FEES` e `ESTIMATED_FEES`.
  - Taxa estimada fallback de 0.10% (0.0010) aplicada quando a exchange reporta zero ou omite comissão.
  - Dedução estrita de todas as taxas no `NET_PNL`.
- *Rastreamento de Slippage por Fill sem Dupla Contagem*:
  - Registro de `reference_price` no instante da intenção e comparação com `average_fill_price`.
  - Slippage registrado em USDT e bps para BUY e SELL.
  - Documentação metodológica: o slippage já compõe o preço de fill do trade; não é deduzido novamente do PnL, evitando dupla contagem.
- *Métricas Financeiras Derivadas Auditadas*:
  - Exclusão de ordens canceladas sem preenchimento (`executed_quantity == 0`) da contagem de trades e PnL.
  - PnL não realizado segregado de trades fechados.
  - `profit_factor` padronizado em 999.99 na ausência de perdas (garantindo JSON válido).
  - Cálculo determinístico de `average_win`, `average_loss` e `expectancy`.
- *Preservação Intangível de S1*:
  - Base `data/finbot_testnet_soak.sqlite3` preservada intacta (134 ciclos, 8 fills, 4 trades fechados, 0 UNKNOWN, 0 orphan, 0 API errors).
- *Protocolo de Deploy S2 no PC Forte*:
  - Documentado detalhadamente no `RUNBOOK.md` com banco dedicado `data/finbot_testnet_soak_s2.sqlite3` em modo supervisionado.
- 420 testes automatizados (408 passando e 12 skipped no `.venv` padrão; 420 passando no `.venv-research`). 12 novos testes focados em `tests/test_testnet_soak.py`.
- Preservação integral do ambiente operacional e do Paper Soak Test no PC Forte.

### Spot Testnet Soak & Métricas Operacionais (FASE 8.4C2D)
- *Correção de Qualidade de Dados (Fills Semantics)*:
  - Garantia de que `average_price` / `average_fill_price` é estritamente `None` (ou N/A) quando `executed_quantity == 0` (ordem cancelada não executada não contamina preço médio nem PnL).
  - Preservação segregada de `requested_price` / `limit_price` e `average_fill_price` em todas as estruturas de dados.
- *Testnet Soak Runner Isolado (`src/finbot/testnet_soak.py`)*:
  - Totalmente desacoplado do Paper Runner (`paper.py`), com pipeline completo e fail-closed: Market Data -> Strategy -> Risk Engine -> MarketFilterGuard -> LiveSafetyGate -> GuardedLiveExecutionEngine -> BinanceSpotTestnetOrderAdapter -> Reconciliação -> Storage.
  - Exigência mandatória de `binance_environment == SPOT_TESTNET` e `testnet_execution_enabled == True`.
- *Normalização de Capital da Estratégia (`TESTNET_STRATEGY_CAPITAL`)*:
  - Criação do parâmetro `testnet_strategy_capital` (default 100.00 USDT) para normalizar métricas de rentabilidade e risco, evitando distorções causadas pelo saldo fictício enorme da exchange.
- *Métricas Operacionais e Financeiras Persistentes*:
  - Tabela append-only e checkpoints em SQLite (`data/finbot_testnet_soak.sqlite3`): uptime, cycles, exceptions, api errors, timeouts, reconciliações, unknown orders, orphan orders, duplicate blocks, orders created/filled/canceled/rejected, partial fills.
  - Cálculo determinístico de equity inicial/atual, realized/unrealized/net PnL, taxas, retorno bruto/líquido, max drawdown, win/loss rate, profit factor, média de ganhos/perdas, expectancy, total trades.
  - Rastreamento amostral: `trade_sample_size`, `observation_period_seconds`, `first_trade_at`, `last_trade_at` (sem aprovação automática de gate).
- *Disjuntores de Segurança (Safety Circuit Breakers)*:
  - Disparo de `stop_new_orders = True` sob ordens UNKNOWN não reconciliadas, ordens órfãs, falhas repetidas de autenticação, mismatch de endpoint/ambiente, divergência de saldo, 5 erros consecutivos, violação do Risk Engine ou falha de banco.
  - Leitura e reconciliação continuam operacionais, mas novas ordens são travadas até intervenção do operador.
- *Comandos Operacionais Read-Only*:
  - `python -m finbot.testnet_soak_status`: visualização tabular do status operacional e financeiro do soak sem expor segredos.
  - `python -m finbot.testnet_soak`: entrypoint por padrão em modo PREVIEW (Safe Mode Read-Only).
- 408 testes automatizados (396 passando e 12 skipped no `.venv` padrão; zero chamadas de rede externas nos testes). 17 novos testes focados em `tests/test_testnet_soak.py`.
- Preservação integral do ambiente operacional e do Paper Soak Test no PC Forte.

### Spot Testnet Execution Lifecycle Validation (FASE 8.4C2C)
- Validações externas na Binance Spot Testnet concluídas com sucesso pelo operador:
  1. `BUY MARKET`: `FILLED`, reconciliação confirmada.
  2. `SELL MARKET`: `FILLED`, reconciliação confirmada.
  3. `BUY LIMIT`: `ACKNOWLEDGED`, reconciliada repetidamente enquanto aberta, `CANCEL_PENDING`, `CANCELED`, reconciliação confirmada.
- Produção permaneceu 100% inviolada: `PRODUCTION_ORDERS_SENT = 0`, `PRODUCTION_WRITE_ENABLED = NO`.

### Spot Testnet Operational Validation (FASE 8.4C2B)
- Primeira ordem externa Spot Testnet executada com sucesso e confirmada pelo operador:
  - `ENVIRONMENT = spot_testnet`
  - `SYMBOL = BTC/USDT`
  - `SIDE = BUY`
  - `TYPE = MARKET`
  - `REQUESTED_NOTIONAL = ~6.63 USDT fictícios`
  - `EXECUTED_QUANTITY = 0.00008000 BTC`
  - `ORDER_STATUS = FILLED`
  - `FINAL_STATE = FILLED`
  - `RECONCILIATION_STATUS = CONFIRMED`
  - `TESTNET_ORDERS_SENT = 1`
  - `PRODUCTION_ORDERS_SENT = 0`
  - `PRODUCTION_WRITE_ENABLED = NO`
- Módulo `src/finbot/testnet_order_validation.py` implementado com ferramenta de teste assistido.

### Pre-Flight Operational Command (FASE 8.4C1A)
- Módulo `src/finbot/preflight.py` implementado com o comando operacional `python -m finbot.preflight` para validação pré-voo hermética, segura e unificada antes de qualquer futura micro-ordem real:
  - *Inviolabilidade de Execução Real*: O comando é estruturalmente desprovido de qualquer capacidade de enviar ou cancelar ordens reais (`REAL_ORDERS_SENT = 0`, `ORDER_NETWORK_CALLS = 0`).
  - *Checagem Segura de Credenciais*: Utiliza `WindowsCredentialProvider` para atestar presença de chaves (`CREDENTIAL_STORE = WINDOWS_CREDENTIAL_MANAGER`, `CREDENTIALS = PRESENT/MISSING`) com proibição absoluta de exibição de API Key, Secret, comprimentos de chave ou representação de string.
  - *Autenticação Privada e Consulta de Saldos (Read-Only)*: Executa `get_account_status()` (`BINANCE_PRIVATE_AUTH = PASS/FAIL`) e `get_balances()` (`PRIVATE_BALANCE_READ = PASS/FAIL`) sem exibir ou persistir qualquer valor patrimonial em tela ou logs.
  - *Metadados Públicos e Filtros CCXT*: Carrega dados públicos de `BTC/USDT` (`symbol`, `min_amount`, `step_size`, `price_tick`, `min_notional`) e os valida através do `MarketFilterGuard` (`MARKET_FILTER_GUARD = PASS/FAIL`).
  - *Cálculo Dinâmico de Micro-Ordem Candidata*: Função `calculate_micro_order_candidate` respeita `minNotional`, `minQty`, `stepSize`, `price_step`, inclui margem defensiva (~15% acima do mínimo) e respeita estritamente o teto `live_micro_order_max_notional` (15.0 USDT). Se impossível, emite `SAFE_MICRO_ORDER_POSSIBLE = NO`.
  - *Verificação Passiva de Suficiência de Fundos*: Verifica se o saldo livre em USDT cobre o notional da candidata (`FUNDS_AVAILABLE_FOR_CANDIDATE = YES/NO`) sem divulgar valores numéricos.
  - *Pipeline Simulado em Modo DRY_RUN*: Submete a intenção candidata ao pipeline real (`LiveSafetyGate` + `DryRunExecutionEngine`), confirmando conformidade técnica com status `SIMULATED_ACCEPTED`.
  - *Verificação de Barreiras Locais*: Valida localmente que `real_order_submission_enabled == False` (`FINAL_LIVE_BARRIER = PASS`) e que `create_order` e `cancel_order` levantam `LiveTradingBlockedError` (`CREATE_ORDER_BARRIER = PASS`, `CANCEL_ORDER_BARRIER = PASS`).
  - *Critério Rígido de Prontidão*: Emite `READY_FOR_8_4C2 = YES` exclusivamente se todas as 11 checagens forem aprovadas.
- Preservação integral do ambiente operacional e do Paper Soak Test de 72 horas no PC Forte.

### Guarded Live Order Executor Foundation (FASE 8.4B)
- Módulo `src/finbot/live_executor.py` implementado com a infraestrutura defensiva do executor LIVE para futuras operações na Binance Spot:
  - *Entrada Estritamente Filtrada*: `GuardedLiveExecutionEngine` consome **exclusivamente** `ApprovedOrderIntent`. Qualquer tentativa de submeter `OrderIntent` cru, `RejectedOrderIntent` ou estruturas arbitrárias resulta em rejeição fail-closed imediata (`InvalidExecutionIntentError`).
  - *Triple Live Arming (Tripla Trava de Armamento)*:
    1. `trading_mode == 'live'`
    2. `live_trading_acknowledged == True`
    3. `live_execution_enabled == True` (Default mandatório: `False`)
    - Se qualquer uma dessas condições for falsa, a execução é categoricamente bloqueada com `LiveExecutionArmingError`.
  - *Micro-Order Cap Dedicado*:
    - Configuração `live_micro_order_max_notional` (default conservador: 15.0 USDT) separada de `live_max_order_notional` (100 USDT).
    - Se o valor nocional exceder o teto, a ordem é rejeitada com `MicroOrderCapExceededError`. É categoricamente proibido reduzir ou alterar o tamanho da ordem automaticamente.
  - *Protocolo de Adapter e Injeção Obrigatória*:
    - Protocolo `ExchangeOrderAdapter` desacopla completamente o motor da rede (`submit_order`, `cancel_order`, `fetch_order_status`).
    - `FakeExchangeOrderAdapter` para testes unitários isolados, suportando injeção de preenchimentos, recusas e timeouts simulados.
    - O executor exige injeção explícita de `ExchangeOrderAdapter` no construtor; não instancia implicitamente conexões de rede ou `BinancePrivateExchange`.
  - *Trava Final da Fase e Inviolabilidade da Binance*:
    - `BinanceOrderAdapter` protegido por trava explícita: `real_order_submission_enabled == False` (default mandatório).
    - Qualquer tentativa de submeter ou cancelar ordem via `BinanceOrderAdapter` levanta imediatamente `RealOrderSubmissionBlockedError` antes de qualquer chamada HTTP / CCXT.
    - `BinancePrivateExchange.create_order()` e `cancel_order()` continuam bloqueados levantando `LiveTradingBlockedError`.
    - Prova arquitetural sentinela aprovada em `test_phase_8_4b_cannot_reach_real_binance_order_endpoint`.
  - *Princípio Soberano de Falha Ambígua*:
    - Axioma fundamental: `UNKNOWN != FAILED` e `TIMEOUT != SAFE TO RETRY`.
    - Timeouts de rede após envio resultam no estado `UNKNOWN`.
    - Proibição absoluta de retry automático cego. Reconciliação via `reconcile_order(client_order_id)` é obrigatória antes de qualquer decisão.
  - *Máquina de Estados de Ciclo de Vida da Ordem (`OrderStatus`)*:
    - Estados: `PREPARED`, `PENDING_SUBMISSION`, `SUBMITTED`, `ACKNOWLEDGED`, `PARTIALLY_FILLED`, `FILLED`, `CANCEL_PENDING`, `CANCELED`, `REJECTED`, `UNKNOWN`.
    - Estado `PENDING_SUBMISSION` persistido no SQLite antes da submissão com `correlation_id` e `client_order_id` gerado deterministicamente (`finbot_<sha256[:28]>`).
    - Idempotência rigorosa impedindo submissões duplicadas.
  - *Fluxo de Cancelamento Seguro*:
    - `cancel_order(client_order_id)` exige ordem conhecida e status cancelável (`SUBMITTED`, `ACKNOWLEDGED`, `PARTIALLY_FILLED`).
    - Bloqueia cancelamento de ordens já `FILLED` (`OrderNotCancelableError`) e exige reconciliação prévia caso esteja em `UNKNOWN` (`AmbiguousExecutionError`).
  - *Auditoria Local Segura*:
    - Persistência em SQLite append-only nas tabelas `live_orders` e `live_order_lifecycle` via `LiveOrderStorage`.
    - Registro de cada transição de estado (`previous_status`, `new_status`, `timestamp`, `reason`) sem exposição de API Keys, secrets ou senhas.
- 336 testes automatizados (324 passando e 12 skipped no `.venv` padrão; zero chamadas de rede). 22 novos testes em `tests/test_live_executor.py`.
- Preservação integral do ambiente operacional e do Paper Soak Test de 72 horas no PC Forte.

### Live Execution Engine / Dry-Run (FASE 8.4A)
- Módulo `src/finbot/execution.py` implementado com pipeline completo de execução simulada (Dry-Run), validando a geração de payload e idempotência sem chamadas à exchange:
  - *Separação Conceitual Obrigatória*:
    - **`APPROVED ORDER INTENT != REAL ORDER`**: Uma intenção aprovada atesta apenas a conformidade teórica com regras e limites; a execução real continua inexistente e categoricamente bloqueada nesta fase.
    - **`DRY_RUN != PAPER TRADING`**: O *Paper Trading* simula dinamicamente a evolução patrimonial e posições abertas ao longo do tempo (ciclos de 1m). O *Dry-Run Execution Engine* valida estritamente a integridade do pipeline técnico de submissão (serialização de payload, idempotência local, limites e precisão da exchange) **sem preenchimento financeiro (fill) e sem mutação patrimonial**.
  - *DryRunExecutionEngine*: Consome **exclusivamente** `ApprovedOrderIntent`. Qualquer tentativa de submeter `OrderIntent` cru, `RejectedOrderIntent` ou estruturas arbitrárias resulta em rejeição fail-closed imediata (`InvalidExecutionIntentError`).
  - *Modos de Execução*: Enum `ExecutionMode` suporta exclusivamente `DRY_RUN`. Tentativas de configurar ou executar em `LIVE` disparam `LiveExecutionBlockedError`.
  - *DryRunOrderResult Imutável*: Dataclass frozen contendo `correlation_id`, `client_order_id`, `symbol`, `side`, `order_type`, `quantity`, `price`, `notional`, `status`, `created_at`, `safety_reason`, `execution_mode`, `order_payload`. Status explícitos `SIMULATED_ACCEPTED` e `DUPLICATE_INTENT`. O status `FILLED` é expressamente proibido no construtor.
  - *Client Order ID Determinístico*: Função `generate_client_order_id` gera identificadores no formato `finbot_<sha256[:28]>` (35 caracteres), em conformidade estrita com o limite de 36 caracteres e formato da Binance Spot (`[a-zA-Z0-9-_]`), sem segredos nem quebra de idempotência.
  - *Idempotência e Persistência Local*: Classe `DryRunStorage` com persistência append-only em SQLite (`dry_run_orders`), garantindo que intenções repetidas retornem `DUPLICATE_INTENT` sem gerar segunda execução lógica, mesmo após reinicializações.
  - *Order Payload Builder*: Função pura `build_order_payload` constrói o payload canônico para o adapter CCXT preservando precisão decimal, sem dependência de credenciais ou rede.
  - *Orquestrador de Pipeline*: `run_dry_run_pipeline` garante que se o `LiveSafetyGate` rejeitar, o `DryRunExecutionEngine` nunca é chamado.
  - *Inviolabilidade de Trading Real*: `create_order` e `cancel_order` permanecem bloqueados levantando `LiveTradingBlockedError` em `BinancePrivateExchange`. Prova arquitetural sentinela aprovada em `test_phase_8_4a_has_zero_live_order_capability`.
- 314 testes automatizados (302 passando e 12 skipped no `.venv` padrão; zero chamadas de rede). 25 novos testes em `tests/test_execution.py`.
- Preservação integral do ambiente operacional e do Paper Soak Test de 72 horas no PC Forte.

### Live Execution Safety Foundation (FASE 8.3)
- Módulo `src/finbot/live_safety.py` implementado com fundação defensiva preliminar antes de qualquer futura execução de ordens Binance Spot:
  - *Fluxo Categórico com Separação de Responsabilidades*:
    `SIGNAL -> ORDER INTENT -> RISK ENGINE -> MARKET FILTER GUARD -> STATE RECONCILIATION -> LIVE SAFETY GATE -> APPROVED INTENT`
  - *Princípio Soberano*: **APPROVED INTENT != EXECUTED ORDER**. Uma intenção aprovada atesta apenas a conformidade teórica com regras e limites; a execução real continua inexistente e categoricamente bloqueada nesta fase.
  - *OrderIntent Imutável*: Dataclass frozen com validação rigorosa no construtor (rejeição de campos vazios, números não positivos, `NaN` e infinitos). Não referencia a exchange nem possui métodos de envio.
  - *MarketFilterGuard*: Extração dinâmica de limites a partir do CCXT (`limits` e `precision`) e `info.filters` da Binance. Funções puras em `Decimal` (`sanitize_amount`, `sanitize_price`, `validate_notional`). Truncamento estrito para passos válidos (`stepSize`, `tickSize`). Proibição categórica de inflar quantidades para bater mínimos (se menor que o mínimo, rejeita com `BELOW_MIN_AMOUNT` / `BELOW_MIN_NOTIONAL`).
  - *StateReconciler e AccountStateSnapshot*: Validação passiva de suficiência patrimonial (BUY exige saldo quote livre; SELL exige saldo base livre). Se insuficiente ou ausente, rejeita imediatamente (`INSUFFICIENT_QUOTE_BALANCE`, `INSUFFICIENT_BASE_BALANCE`, `MISSING_ACCOUNT_STATE`). Proibição total de correção automática de saldo, posições sintéticas ou vendas forçadas.
  - *Soberania Absoluta do Risk Engine*: O `LiveSafetyGate` consome a decisão do Risk Engine existente (`src/finbot/risk.py`). Se o Risk Engine rejeitar, o gate rejeita. Não existe override, bypass ou `force=true`.
  - *Hard Live Limit Operacional*: `live_max_order_notional` (default conservador: 100 USDT) configurável em `src/finbot/config.py`. Se o valor nocional da ordem exceder o limite, rejeição imediata (`EXCEEDS_LIVE_MAX_NOTIONAL`) sem truncamento automático.
  - *Autorização Explícita*: `live_trading_acknowledged` (default mandatório: `False`) configurável em `src/finbot/config.py`. Exige `trading_mode == 'live'` E `live_trading_acknowledged == True` para elegibilidade, sem habilitar submissão de ordens.
  - *Semântica de AccountStatus / API Permissions*: Investigação concluiu que `can_trade`/`can_withdraw` do endpoint `/api/v3/account` representam KYC/AML da conta mestra, e NÃO permissões da API Key específica. Decisão formal: NÃO utilizá-los como gate de autorização.
  - *Auditoria Local Segura*: Classe `LiveSafetyAuditStorage` com persistência append-only em SQLite (`live_safety_decisions`) gravando exclusivamente dados operacionais não sensíveis (sem chaves de API, segredos ou credenciais).
  - *Inviolabilidade de Trading Real*: `create_order` e `cancel_order` permanecem bloqueados levantando `LiveTradingBlockedError` em `BinancePrivateExchange`. Prova arquitetural sentinela aprovada em `test_phase_8_3_cannot_submit_real_orders`.
- 289 testes automatizados (277 passando e 12 skipped no `.venv` padrão; zero chamadas de rede). 22 novos testes em `tests/test_live_safety.py`.
- Preservação integral do ambiente operacional e do Paper Soak Test de 72 horas no PC Forte.

### Binance Private API Read-Only Validation (FASE 8.2C)
- Homologação operacional realizada e validada com sucesso no ambiente oficial do PC Forte (`C:\Projetos\FinBot`):
  - *Checkpoint Operacional Oficial*:
    ```text
    BINANCE_PRIVATE_AUTH = PASS
    BINANCE_PRIVATE_BALANCE_READ = PASS
    CREDENTIAL_STORAGE = WINDOWS_CREDENTIAL_MANAGER
    LIVE_ORDER_EXECUTION = BLOCKED
    WITHDRAWALS = DISABLED
    TRANSFERS = DISABLED
    PAPER_SOAK = PRESERVED
    ```
  - *Validação de Armazenamento e Integridade*: Credenciais lidas com sucesso do Windows Credential Manager (`target=FinBot/Binance/Production`, status `PRESENT`). Validação estrutural confirmou API Key (64 caracteres) e API Secret (64 caracteres) íntegros, sem espaços em branco nas extremidades.
  - *Causa Raiz e Solução do Erro -1022*: A falha de assinatura anterior ("Signature for this request is not valid.") foi formalmente diagnosticada como truncamento no terminal legado (`getpass` colou apenas 2 caracteres do secret). O re-cadastro seguro via GUI Tkinter da Fase 8.2B (`python -m finbot.credentials_gui`) corrigiu definitivamente as chaves.
  - *Autenticação Privada Real*: Chamada a `BinancePrivateExchange.get_account_status()` concluída com status `PASS`.
  - *Consulta Privada de Saldos*: Chamada a `BinancePrivateExchange.get_balances()` concluída com status `PASS` (ativos carregados com sucesso; valores nominais e quantidades estritamente preservados fora do repositório).
  - *Perímetro de Segurança da Chave Binance*: Permissão estrita Read-Only, restrição por IP (IP restriction) configurada para o PC Forte, trading desabilitado, saídas/saques desabilitados (zero withdrawals) e transferências desabilitadas (zero transfers).
  - *Inviolabilidade de Trading Real*: Nenhuma ordem foi criada ou cancelada; nenhum endpoint de trading foi invocado. `create_order` e `cancel_order` permanecem levantando `LiveTradingBlockedError`.
  - *Paper Soak Test*: Continua em execução ininterrupta de 72 horas no PC Forte.

### GUI Local Segura para Cadastro de Credenciais (FASE 8.2B)
- Módulo `src/finbot/credentials_gui.py` implementado com Tkinter nativo (Python Standard Library, zero novas dependências):
  - *Interface Gráfica Local*: Janela "FinBot — Binance Credentials" simples, local e segura, criada especificamente para eliminar erros de colagem e digitação oculta observados no terminal via `getpass` (incidente real no PC Forte onde `SECRET_LEN=2` gerou erro -1022 na Binance).
  - *Máscara Visual Estrita*: API Secret mascarado por padrão com `show="*"`, com alternância visual controlada ("Mostrar API Secret") para conferência opcional do operador antes do salvamento.
  - *Validação Preventiva Segura*: Rejeição de campos vazios, espaços em branco puros, quebras de linha e salvaguarda contra chaves/segredos truncados (`len < 16`), impedindo repetição do erro `SECRET_LEN=2` sem assumir tamanhos rígidos arbitrários.
  - *Armazenamento Exclusivo no Windows Credential Manager*: Integração 100% direta com `WindowsCredentialProvider` (target canônico `FinBot/Binance/Production`).
  - *Isolamento Estrito de Rede e Arquivos*: O ato de salvar na GUI não realiza nenhuma chamada à Binance (cadastro e teste permanecem separados). Proibição total de gravação em `.env`, `.json`, `.yaml`, SQLite, CSV ou logs.
  - *Limpeza Imediata em Memória*: Campos de entrada e variáveis de controle limpos imediatamente na GUI após salvamento bem-sucedido.
  - *CLIs de Invocação*: Ponto de entrada dedicado `python -m finbot.credentials_gui` e ação integrada `python -m finbot.credentials gui`. Comandos existentes `status`, `setup` e `remove` continuam funcionando integralmente.
- 267 testes automatizados (255 passando e 12 skipped no `.venv` padrão; 267 passando 100% no `.venv-research`). 16 novos testes em `tests/test_credentials_gui.py`.

### Secure Windows Credential Storage (FASE 8.2A)
- Módulo `src/finbot/credentials.py` implementado com arquitetura de provedores de credenciais e proteção estrita contra vazamento:
  - *Armazenamento Oficial de Produção*: **Windows Credential Manager** via `WindowsCredentialProvider`, utilizando a API nativa do Windows (`Advapi32.dll` via `ctypes`: `CredReadW`, `CredWriteW`, `CredDeleteW`, `CredFree`) sob o target canônico `FinBot/Binance/Production`.
  - *Proibição Absoluta de Arquivos e Variáveis de Ambiente*: Credenciais de produção NÃO são aceitas nem lidas de `.env`, `.json`, `.yaml`, `.toml`, SQLite, CSV, logs ou variáveis de ambiente (`BINANCE_API_KEY`/`BINANCE_API_SECRET`).
  - *Estrutura Blindada em Memória*: Dataclass `BinanceCredentials` implementa `repr=False` e mascaramento customizado `__repr__` e `__str__` (`[PROTECTED]`), impedindo exposição em logs, dumps, terminal ou inspeções de objetos.
  - *Provedor para Testes Automatizados*: `FakeCredentialProvider` em memória permite testes unitários determinísticos, sem tocar no Credential Manager do sistema nem depender da Binance.
  - *Princípio Fail-Closed*: Se as credenciais estiverem ausentes no Windows Credential Manager, lança `CredentialsMissingError` imediatamente, sem chamada de rede, sem fallback para paper e sem tentativa de ordens.
  - *CLI Administrativa Segura*: Comandos `python -m finbot.credentials` (`setup` com senha oculta via `getpass`, `status` sem expor segredos, `remove` com confirmação explícita).
  - *Preservação do Modo Paper*: O modo `paper` (`TRADING_MODE=paper`) permanece 100% desacoplado e não consulta o Windows Credential Manager.

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
- D030: Secure Local Credential Enrollment GUI (Fase 8.2B).
- D031: Binance Private API Read-Only Operational Validation (Fase 8.2C).
- D032: Live Execution Safety Foundation (Fase 8.3).
- D033: Dry-Run Live Execution Engine (Fase 8.4A).
- D034: Guarded Live Order Execution Foundation (Fase 8.4B).
- D035: Comando Operacional de Pre-Flight e Validação Hermética de Prontidão (Fase 8.4C1A).
- D036: Binance Spot Testnet Integration & Production Isolation (Fase 8.4C2A).
- D037: Assisted Spot Testnet Order Validation & Institutional Live Capital Gate Policy (Fase 8.4C2B).
- D038: Binance Spot Testnet Execution Lifecycle Validation (Fase 8.4C2C).
- D039: Binance Spot Testnet Soak Runner, Normalized Strategy Capital & Operational Metrics (Fase 8.4C2D).
- D040: Testnet Soak Hardening, Heartbeat Observability, Realistic Cost Accounting & PC Forte S2 Protocol (Fase 8.4C2E).

## Último checkpoint
FASE 8.4C2E — Testnet Soak Hardening & PC Forte Deployment Readiness CONCLUÍDA: Sistema endurecido com observabilidade dinâmica de status do runner via heartbeat (timeout 180s, estados READY/IDLE, RUNNING, STOPPED, CIRCUIT_BREAKER_TRIPPED), graceful shutdown via KeyboardInterrupt/Ctrl+C persistindo status STOPPED e fechando conexões SQLite limpas sem corrupção, restart seguro com reconciliação pré-ciclo mandatória (`reconcile_pre_cycle_state`) de ordens não terminais e reconstrução de posição local validada contra a exchange antes de invocar Strategy/Risk Engine, segregação contábil realista de taxas (exchange-reported vs fallback estimado de 0.10%) com dedução estrita no Net PnL, rastreamento determinístico de slippage por fill em USDT e bps com metodologia de não dupla contagem (já embutido no fill price), e cálculo auditado de métricas derivadas (profit factor 999.99 para ausência de perdas, average win/loss, expectancy). Base de dados de S1 preservada intacta em `data/finbot_testnet_soak.sqlite3` (134 ciclos, 8 fills, 4 trades fechados, 0 UNKNOWN, 0 orphan, 0 API errors, posição NONE). Protocolo de deploy do S2 (24 horas supervisionadas) no PC Forte com banco próprio `data/finbot_testnet_soak_s2.sqlite3` documentado no `RUNBOOK.md`. Formalização arquitetural do ADR D040 em `DECISIONS.md`. 420 testes automatizados passando com 100% de sucesso em `.venv` e `.venv-research`. Zero ordens reais enviadas (`PRODUCTION_ORDERS_SENT = 0`, `PRODUCTION_WRITE_ENABLED = NO`). PC Forte e Paper Soak intocados.

## Próxima etapa (NEXT)
FASE 8.4C2E / S2 — Execução Supervisionada de 24 Horas do Testnet Soak no PC Forte:
1. Operador autoriza e realiza o push do código para o GitHub (`git push origin main`).
2. No PC Forte, executar `git pull origin main` e validar integridade via `python -m unittest discover tests`.
3. Executar preflight check (`python -m finbot.testnet_preflight`).
4. Executar preview read-only apontando para o banco S2 (`python -m finbot.testnet_soak --db-path data/finbot_testnet_soak_s2.sqlite3`).
5. Executar ciclo único `--once` com banco S2 para validar inicialização e schema (`python -m finbot.testnet_soak --once --db-path data/finbot_testnet_soak_s2.sqlite3`).
6. Iniciar a execução contínua supervisionada de 24 horas (`python -m finbot.testnet_soak --continuous --interval-seconds 60 --db-path data/finbot_testnet_soak_s2.sqlite3`).



