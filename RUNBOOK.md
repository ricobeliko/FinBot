# FinBot — Runbook Operacional

Procedimentos operacionais básicos e diretos para o ambiente local.

---

## 1. Navegar até o Projeto

```powershell
cd D:\Projetos\FinBot
```

---

## 2. Ativar Ambiente Virtual

No PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

---

## 3. Verificar Ambiente e Ferramentas

```powershell
python --version
pip --version
git status
```

---

## 4. Instalar Projeto Localmente em Modo Editável

```powershell
python -m pip install -e .
```

---

## 5. Executar Market Monitor (FASE 2 / 3)

Com o ambiente ativado:

```powershell
python -m finbot.main
```

Consulta dados públicos de ticker e 20 candles de 1m na Binance Spot (BTC/USDT) e calcula o sinal operacional determinístico (`BUY`, `SELL`, `HOLD`) por cruzamento de médias (SMA 5 / SMA 10). Os registros são exibidos no console e gravados em `logs/finbot.log`.

---

## 6. Executar Backtesting Reproduzível (FASE 4)

Com o ambiente ativado:

```powershell
python -m finbot.backtest
```

Executa a simulação histórica reproduzível da estratégia SMA Crossover sobre o snapshot local salvo em `data/backtest/binance_BTCUSDT_5m.json` (500 candles de 5m da Binance Spot). Exibe relatório no terminal com retorno da estratégia, Buy & Hold, trades, taxa de acerto (win rate), drawdown máximo e profit factor.

Para forçar atualização/novo download do snapshot histórico:
```powershell
python -m finbot.backtest --refresh
```

---

## 7. Executar Paper Trading com Risk Engine (FASE 6)

Com o ambiente ativado:

Executa um ciclo one-shot de simulação em tempo real sobre dados públicos passando pela validação do Risk Engine:
```powershell
python -m finbot.paper
```

Consulta o saldo, posições, histórico e métricas de risco sem acessar a internet (offline):
```powershell
python -m finbot.paper --status
# ou com foco em telemetria do soak test:
python -m finbot.paper --soak-status
```

Ativa o Kill Switch localmente (bloqueia novos BUYs mantendo permissão de saída):
```powershell
python -m finbot.paper --kill-switch on
```

Desativa o Kill Switch localmente (restaura operação normal):
```powershell
python -m finbot.paper --kill-switch off
```

Restaura o saldo inicial fictício (10000.00 USDT), zera as operações simuladas e limpa o estado de risco e telemetria:
```powershell
python -m finbot.paper --reset --yes
```

---

## 8. Executar Dashboard Visual Local (FASE 7)

Com o ambiente ativado:

```powershell
streamlit run src/finbot/dashboard.py --server.address=127.0.0.1
# ou via script operacional:
powershell -ExecutionPolicy Bypass -File scripts\run_dashboard.ps1
```

Inicia o dashboard visual local em `http://127.0.0.1:8501`.
- **Modo**: 100% Read-Only (visualização de patrimônio, posições, P/L, trades, Risk Engine, Runner Health e frescor do Paper Runner).
- **Rede**: Estritamente local (`127.0.0.1`), sem exposição para rede externa ou internet.
- **Resiliência Offline**: Se a internet estiver indisponível, o painel carrega todos os dados locais do SQLite normalmente.
- **Encerramento**: Pressione `Ctrl + C` no terminal para parar o servidor Streamlit.

---

## 9. Scripts Operacionais e Automação (FASE 7.5 / 7.6)

### 9.1 Diagnóstico de Integridade Local
```powershell
powershell -ExecutionPolicy Bypass -File scripts\check_finbot.ps1
```
Valida Python, virtualenv, SQLite, status do Paper Trading, ausência de remotes Git e status detalhado da tarefa agendada no Windows.

### 9.2 Execução de Ciclo Individual One-Shot
```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_paper.ps1
```
Invoca `finbot.paper` utilizando o Python da `.venv` sem abrir shell interativo e preservando o código de saída.

### 9.3 Instalar Tarefa Agendada no Windows Task Scheduler
```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_paper_task.ps1
```
Registra a tarefa `FinBot Paper Runner` para o usuário local, com periodicidade de 1 minuto, política anti-concorrência `IgnoreNew` e timeout de 5 minutos.

### 9.4 Remover Tarefa Agendada do Windows Task Scheduler
```powershell
powershell -ExecutionPolicy Bypass -File scripts\remove_paper_task.ps1
```
Desregistra e remove com segurança a tarefa do agendador do Windows.

---

## 10. Executar Testes Unitários

```powershell
python -m unittest discover tests
```

Executa toda a bateria de testes unitários determinísticos (70 testes cobrindo Exchange, Strategy, Backtest, Storage, Risk Engine, Metrics, Automated Paper Runner, isolamento de rede e rotação de logs sem conexão de internet e sem dados privados).

---

## 11. Validar Compilação do Código

```powershell
python -m compileall src tests
```

---

## 12. Fluxo de Sincronização entre Notebook e PC Forte (GitHub Privado)

O repositório privado (`https://github.com/ricobeliko/FinBot.git`) é utilizado unicamente para backup e transferência de código, sem CI/CD ou automações na nuvem.

### 12.1 No Notebook (Desenvolvimento)
Após implementar e validar alterações locais:
```powershell
git status
git add .
git commit -m "mensagem descritiva"
git push origin main
```

### 12.2 No PC Forte (Testes Locais e Runtime 24/7)
Para receber novas atualizações e validar antes de executar:
```powershell
git pull origin main
python -m unittest discover tests
python -m finbot.backtest
powershell -ExecutionPolicy Bypass -File scripts\check_finbot.ps1
```

> **Nota Operacional**: O banco de dados operacional SQLite (`data/finbot_paper.sqlite3`), logs e eventuais arquivos `.env` são ignorados no Git e pertencem estritamente à máquina local em que o bot está executando.

---

## 13. Procedimento Operacional: Binance Read-Only Validation (FASE 8.2C)

Procedimento seguro para validação operacional da conexão autenticada em modo estritamente **Read-Only** no ambiente autorizado (PC Forte).

### 13.1 Verificar Status das Credenciais no Windows Credential Manager
```powershell
python -m finbot.credentials status
```
- Deve reportar `Credential store: Windows Credential Manager` e `Binance credentials: PRESENT`.
- Se reportar `MISSING`, realize o cadastro seguro conforme o passo seguinte.

### 13.2 Cadastrar ou Atualizar Credenciais via GUI Segura (se necessário)
```powershell
python -m finbot.credentials_gui
```
- Cole a API Key e o API Secret nos respectivos campos.
- O campo API Secret permanece mascarado por padrão (`show="*"`); use a opção "Mostrar API Secret" apenas para conferência visual prévia antes de salvar.
- A GUI valida o comprimento preventivo e grava diretamente no Windows Credential Manager sob o target `FinBot/Binance/Production`.

### 13.3 Testar Leitura de Status da Conta (Read-Only)
```powershell
python -c "from finbot.private_exchange import BinancePrivateExchange; ex = BinancePrivateExchange(); st = ex.get_account_status(); print(f'Account Status: OK | Tipo: {st.account_type} | canTrade: {st.can_trade}')"
```
- Valida a conectividade autenticada HMAC com a Binance Spot.
- Exibe apenas o tipo de conta e flag descritivo, sem expor chaves ou segredos.

### 13.4 Testar Consulta Privada de Saldos (Read-Only)
```powershell
python -c "from finbot.private_exchange import BinancePrivateExchange; ex = BinancePrivateExchange(); b = ex.get_balances(); print(f'Balance Query: OK | Total de ativos com saldo: {len(b)}')"
```
- Reconcilia a capacidade de consulta privada de ativos da conta.
- Não expõe quantias patrimoniais no terminal.

### 13.5 Regras Mandatórias de Segurança Operacional
- **NUNCA imprimir credenciais** no terminal, scripts ou saídas de depuração.
- **NUNCA passar credenciais como argumentos** de linha de comando (`--api-key`, etc.).
- **NUNCA salvar chaves ou segredos em arquivos** (`.env`, `.json`, `.yaml`, `.txt`, `.sqlite3`, `.csv` ou logs).
- **NUNCA registrar valores reais de saldo ou quantidades financeiras** em relatórios versionados ou issues.
- **Trading real bloqueado**: `create_order` e `cancel_order` permanecem desabilitados com bloqueio arquitetural inviolável (`LiveTradingBlockedError`).

---

## 14. Procedimento Operacional: Pre-Flight de Prontidão (FASE 8.4C1)

Procedimento seguro de validação operacional read-only preliminar, executado no ambiente de produção (PC Forte) antes de qualquer autorização de micro-ordem real.

### 14.1 Executar Comando Pre-Flight
Com o ambiente ativado:
```powershell
python -m finbot.preflight
# ou diretamente via executável da virtualenv:
.\.venv\Scripts\python.exe -m finbot.preflight
```

### 14.2 O que o Pre-Flight valida (100% Read-Only)
1. **Credenciais**: Presença e integridade das chaves no Windows Credential Manager (`target=FinBot/Binance/Production`). Zero segredos impressos.
2. **Autenticação Privada**: Conexão com Binance Spot via `get_account_status()` (`BINANCE_PRIVATE_AUTH = PASS`).
3. **Leitura de Saldos**: Consulta privada via `get_balances()` (`PRIVATE_BALANCE_READ = PASS`). Nenhum saldo numérico é exibido ou persistido.
4. **Filtros de Mercado**: Consulta pública dos filtros atuais de `BTC/USDT` no CCXT (`minQty`, `stepSize`, `tickSize`, `minNotional`).
5. **MarketFilterGuard**: Validação dos filtros extraídos contra as regras defensivas de mercado.
6. **Micro-Ordem Candidata**: Cálculo estrito de quantidade e preço com margem defensiva acima de `minNotional` e estritamente abaixo do teto `live_micro_order_max_notional` (15.0 USDT).
7. **Suficiência de Fundos**: Verificação passiva se o saldo livre de USDT cobre o notional da candidata (`FUNDS_AVAILABLE_FOR_CANDIDATE = YES`).
8. **Simulação Dry-Run**: Envio da intenção candidata pelo pipeline defensivo completo (`LiveSafetyGate` + `DryRunExecutionEngine`), confirmando status `SIMULATED_ACCEPTED`.
9. **Barreira Final**: Validação local e sem rede de que `real_order_submission_enabled == False`.
10. **Barreiras de Ordens**: Confirmação estrutural de que `create_order` e `cancel_order` levantam `LiveTradingBlockedError`.

### 14.3 Critério Mandatório de Prontidão
A execução futura da **FASE 8.4C3** (micro-ordem assistida de produção com o operador) só é autorizada se o relatório final emitir:
```text
READY_FOR_8_4C2 = YES
```
Se qualquer checagem falhar ou emitir `NO`, o sistema permanece categoricamente bloqueado.

---

## 15. Procedimento Operacional: Binance Spot Testnet (FASE 8.4C2)

Ambiente oficial de testes (Sandbox) da Binance Spot (`https://testnet.binance.vision`) para validação prática do pipeline de execução real de ordens sem risco financeiro.

### 15.1 Cadastrar Credenciais da Testnet (Windows Credential Manager)
Obtenha as chaves HMAC gratuitas na Binance Spot Testnet oficial (`https://testnet.binance.vision`) via login GitHub.

Cadastrar via GUI segura:
```powershell
python -m finbot.credentials_gui --env spot_testnet
```
- Selecione a opção **BINANCE SPOT TESTNET** na interface gráfica.
- O target exibido será `FinBot/Binance/SpotTestnet`.
- Cole a API Key e o API Secret nos respectivos campos e salve.

Ou cadastrar via CLI oculta:
```powershell
python -m finbot.credentials setup --env spot_testnet
```

### 15.2 Verificar Status das Credenciais da Testnet
```powershell
python -m finbot.credentials status --env spot_testnet
```
- Deve reportar:
  - `Credential store: Windows Credential Manager`
  - `Target: FinBot/Binance/SpotTestnet`
  - `Binance credentials: PRESENT`

### 15.3 Executar Testnet Pre-Flight (100% Read-Only)
Com o ambiente ativado:
```powershell
python -m finbot.testnet_preflight
# ou diretamente via executável:
.\.venv\Scripts\python.exe -m finbot.testnet_preflight
```
O comando valida de forma estritamente read-only:
1. `CREDENTIAL_STORE`: Windows Credential Manager.
2. `TESTNET_CREDENTIALS`: Presença no target `FinBot/Binance/SpotTestnet`.
3. `TESTNET_AUTH`: Conectividade e autenticação HMAC em `testnet.binance.vision`.
4. `TESTNET_BALANCE_READ`: Leitura segura de saldos fictícios (sem expor quantias).
5. `TESTNET_MARKET_METADATA`: Consulta pública de filtros de `BTC/USDT` na Testnet.
6. `RISK_ENGINE`: Avaliação pelo motor soberano de risco.
7. `MARKET_FILTER_GUARD`: Sanitização e limites de mercado da Testnet.
8. `EXECUTION_BARRIER`: Confirmação de que `testnet_execution_enabled == False` bloqueia escritas.
9. `PRODUCTION_ISOLATION`: Comprovação de que Produção (`api.binance.com`, target `FinBot/Binance/Production`, ordens e transferências) permanece 100% isolada, intocada e bloqueada.

Veredito emitido:
```text
READY_FOR_TESTNET_ORDER = YES / NO
```
Zero ordens são enviadas durante o Pre-Flight (`TESTNET_ORDERS_SENT = 0`, `PRODUCTION_ORDERS_SENT = 0`).

---

## 16. Procedimento Operacional: Validação de Ciclo de Vida Spot Testnet (FASES 8.4C2B e 8.4C2C)

Ferramenta operacional assistida para validação dos ciclos essenciais de execução na Binance Spot Testnet oficial (`https://testnet.binance.vision`) utilizando capital fictício.

### 16.1 Estado Consolidado da Primeira Ordem (FASE 8.4C2B — CONCLUÍDA)
A primeira emissão de compra na Spot Testnet foi executada com sucesso e confirmada pelo operador:
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

---

### 16.2 Validação do Ciclo de Vida (FASE 8.4C2C — EM VALIDAÇÃO OPERACIONAL)

O entrypoint `finbot.testnet_order_validation` suporta o seletor `--action`:
- `sell_market` (padrão conservador): venda assistida do saldo fictício adquirido (`0.00008000 BTC`).
- `limit_cancel`: ciclo completo de colocação de ordem LIMIT abaixo do mercado seguido de cancelamento controlado e reconciliação.
- `buy_market`: ciclo de compra a mercado (regressão da 8.4C2B).

#### 16.2.1 Preview READ-ONLY de SELL MARKET (Padrão)
**Comando seguro sem escrita (`TESTNET_WRITE_EXECUTED = NO`):**
```powershell
python -m finbot.testnet_order_validation --action sell_market
# ou diretamente via executável:
.\.venv\Scripts\python.exe -m finbot.testnet_order_validation --action sell_market
# ou simplesmente:
python -m finbot.testnet_order_validation
```

O comando realiza de forma 100% read-only:
1. Conecta à Spot Testnet e consulta o saldo real disponível de BTC (`get_balances`).
2. Obtém os filtros de mercado vigentes de `BTC/USDT` (`minQty`, `stepSize`, `minNotional`).
3. Consulta o ticker em tempo real via `fetch_ticker`.
4. Dimensiona dinamicamente a quantidade de BTC a vender (limitada ao teto de `0.00008000 BTC`).
5. Valida a intenção através de `RiskEngine`, `MarketFilterGuard` e `check_production_isolation`.
6. Exibe a tela de preview com `TESTNET_WRITE_EXECUTED = NO` e aborta antes de qualquer escrita.

#### 16.2.2 Execução Armada de SELL MARKET na Spot Testnet
Após revisão e aprovação explícita do preview pelo operador:
```powershell
python -m finbot.testnet_order_validation --action sell_market --confirm-testnet-order
```
*Atenção: A flag `--confirm-testnet-order` é estrita e mandatória. Flags genéricas (`--yes`, `--force`, `--live`) são sumariamente rejeitadas.*

#### 16.2.3 Preview READ-ONLY de LIMIT + CANCEL
**Comando seguro sem escrita:**
```powershell
python -m finbot.testnet_order_validation --action limit_cancel
# ou diretamente via executável:
.\.venv\Scripts\python.exe -m finbot.testnet_order_validation --action limit_cancel
```
Exibe o preço limite com 15% de desconto defensivo em relação ao ticker, alinhado ao `tickSize`, a quantidade calculada para ~6 USDT fictícios e atesta `TESTNET_WRITE_EXECUTED = NO`.

#### 16.2.4 Execução Armada de LIMIT + CANCEL na Spot Testnet
Após aprovação do preview pelo operador:
```powershell
python -m finbot.testnet_order_validation --action limit_cancel --confirm-testnet-order
```
O ciclo executa deterministicamente:
1. Validação dos sentries defensivos pré-escrita.
2. Emissão do sinal de armamento: `TARGET_ENVIRONMENT = BINANCE_SPOT_TESTNET`, `PRODUCTION_TARGET = NO`, `TESTNET_WRITE_ARMED = YES`.
3. Submissão da ordem `LIMIT` de compra longe do book com `clientOrderId` determinístico único.
4. Reconciliação do estado aberto (`SUBMITTED`/`ACKNOWLEDGED`).
5. Verificação se a ordem já foi preenchida na exchange:
   - Se já preencheu (`FILLED`), não tenta cancelar cegamente; reconcilia e registra o estado real.
   - Se confirmada aberta, envia a solicitação de cancelamento controlado (`cancel_order`).
6. Reconciliação final confirmando a transição para `CANCELED`.
7. Emissão do relatório operacional sem dados sensíveis.

---

### 16.3 Diretriz Constitucional: Live Capital Gate
**DINHEIRO REAL NÃO SERÁ UTILIZADO APENAS PORQUE O PIPELINE TÉCNICO ESTÁ PRONTO.**
A prontidão técnica do pipeline de execução não autoriza operações com capital real em Produção.
Antes de qualquer escrita em ambiente de Produção com fundos reais, será obrigatória a aprovação formal do **`LIVE_CAPITAL_GATE`**, baseado nos seguintes critérios objetivos:
1. *Estabilidade Operacional*: Zero interrupções não planejadas, crashes ou exceções não tratadas no runtime;
2. *Confiabilidade de Execução*: Taxa de reconciliação de 100%, sem estados ambíguos ou ordens órfãs;
3. *Controle de Drawdown*: Drawdown estritamente dentro dos parâmetros de risco predefinidos;
4. *Amostragem Mínima de Operações*: Amostra estatística significativa de ordens simuladas executadas;
5. *Resultado Líquido Positivo Após Custos*: Rentabilidade líquida comprovada após taxas (maker/taker) e slippage;
6. *Validação Fora da Amostra (Out-of-Sample)*: Robustez em dados não visualizados na calibração;
7. *Paper Trading Prolongado (Paper Soak)*: Conclusão do soaking ininterrupto no PC Forte;
8. *Testnet Soak*: Resiliência a desconexões de rede e reconexões em sandbox da exchange.

*Os thresholds numéricos para cada critério serão definidos em fase posterior específica de governança.*

---

## 17. Procedimentos Operacionais: Binance Spot Testnet Soak & Métricas (Fase 8.4C2D)

### 17.1 Visão Geral e Princípios
A Fase 8.4C2D prepara o FinBot para operação prolongada (soaking) na Binance Spot Testnet com foco em:
- Estabilidade e confiabilidade de longo prazo;
- Observabilidade total e persistência de métricas operacionais e financeiras;
- Disjuntores automáticos de segurança (Circuit Breakers) para proteção do processo;
- Normalização de capital através do conceito de `TESTNET_STRATEGY_CAPITAL` (independente do saldo massivo da exchange);
- Coleta de evidências para o futuro framework `LIVE_CAPITAL_GATE`.

**IMPORTANTE**:
- **NENHUMA OPERAÇÃO CONTÍNUA AUTOMÁTICA É INICIADA SEM AUTORIZAÇÃO HUMANA EXPRESSA.**
- **DINHEIRO REAL PERMANECE INVIOLÁVEL: `PRODUCTION_ORDERS_SENT = 0`, `PRODUCTION_WRITE_ENABLED = NO`.**

### 17.2 Comando READ-ONLY de Status: `finbot.testnet_soak_status`
Comando seguro, estritamente de leitura (sem mutação e sem envio de ordens):
```powershell
python -m finbot.testnet_soak_status
# ou com indicação de banco customizado:
python -m finbot.testnet_soak_status --db-path data/finbot_testnet_soak.sqlite3
```

**Saída esperada**:
```text
================================================================================
                      FINBOT — TESTNET SOAK STATUS REPORT
================================================================================

[OPERATIONAL HEALTH]
  STATUS                       : READY/IDLE / STOPPED / RUNNING
  CIRCUIT_BREAKER_TRIPPED      : NO
  UPTIME                       : 0s (0.0h)
  TOTAL_CYCLES                 : 0
  SUCCESSFUL_CYCLES            : 0
  FAILED_CYCLES                : 0
  API_ERRORS                   : 0
  UNKNOWN_ORDERS               : 0
  ORPHAN_ORDERS                : 0
  DUPLICATE_BLOCKS             : 0

[FINANCIAL & STRATEGY METRICS]
  STRATEGY_CAPITAL             : 100.00 USDT
  STARTING_EQUITY              : 100.00 USDT
  CURRENT_EQUITY               : 100.00 USDT
  REALIZED_PNL                 : 0.00 USDT
  UNREALIZED_PNL               : 0.00 USDT
  NET_PNL                      : 0.00 USDT
  FEES (EXCHANGE REPORTED)     : 0.00000000 USDT
  FEES (ESTIMATED FALLBACK)    : 0.00000000 USDT
  TOTAL FEES                   : 0.00000000 USDT
  NET_RETURN                   : 0.00%
  MAX_DRAWDOWN                 : 0.00%
  TOTAL_TRADES                 : 0
  CLOSED_TRADES                : 0

[PRODUCTION BARRIER SENTINEL]
  TARGET_ENVIRONMENT           : BINANCE_SPOT_TESTNET
  PRODUCTION_ORDERS_SENT       : 0
  PRODUCTION_WRITE_ENABLED     : NO
================================================================================
```

### 17.3 Comando READ-ONLY de Preview: `finbot.testnet_soak`
Por padrão, o entrypoint operacional do soak roda em modo **PREVIEW (Safe Mode Read-Only)**.
Ele avalia dados, verifica sentries, confere saldo e simula um ciclo sem enviar qualquer ordem à Testnet:
```powershell
python -m finbot.testnet_soak
# ou:
.\.venv\Scripts\python.exe -m finbot.testnet_soak
```

### 17.4 Safety Circuit Breakers (Disjuntores Operacionais)
O runner do Testnet Soak monitora e desarma automaticamente (`stop_new_orders = True`) sob:
1. **Ordem UNKNOWN**: Qualquer timeout ou resposta ambígua da exchange não confirmada;
2. **Ordem Órfã**: Inconsistência entre ordens locais e na exchange;
3. **Falhas Repetidas de Autenticação**: 3 tentativas consecutivas com erro de credenciais;
4. **Mismatch de Endpoint / Ambiente**: Detecção de qualquer chamada fora de `testnet.binance.vision`;
5. **Divergência Crítica de Saldo**: Inconsistência entre saldo local e saldo da exchange;
6. **Erros Operacionais Consecutivos**: 5 falhas operacionais consecutivas;
7. **Violação do Risk Engine**: Violação de limites de risco configurados;
8. **Falha de Persistência**: Falha de I/O no banco SQLite local.

Quando disparado:
- `STOP_NEW_ORDERS = TRUE`;
- Reconciliação e leitura continuam ativas para preservar integridade de auditoria;
- Nenhuma nova ordem é emitida até resolução e intervenção explícita do operador humano.

### 17.5 Normalização de Capital (`TESTNET_STRATEGY_CAPITAL`)
A Binance Spot Testnet credita saldos fictícios astronômicos (ex: 5.000.000 USDT ou centenas de BTC).
Para evitar a distorção completa de métricas de retorno, drawdown e dimensionamento, o FinBot utiliza o conceito de **`TESTNET_STRATEGY_CAPITAL`** (default: `100.00 USDT`).
Todas as métricas financeiras (equity, retorno líquido, drawdown, win rate) são calculadas em relação a essa base normalizada e aos trades realizados pela estratégia, assegurando fidelidade estatística para o futuro `LIVE_CAPITAL_GATE`.

---

## 18. Procedimento de Deploy e Execução Supervisionada do S2 (24h) no PC Forte (Fase 8.4C2E)

### 18.1 Visão Geral e Princípios
A Fase 8.4C2E estabelece o protocolo operacional para executar o Soak S2 (24 horas contínuas) no ambiente de hardware dedicado (**PC Forte**), sob supervisão operacional ativa.

**Salvaguardas Mandatórias**:
- **Preservação Integral de S1**: O banco histórico de S1 (`data/finbot_testnet_soak.sqlite3`, 134 ciclos, 8 fills, 4 trades fechados) NÃO pode ser deletado, zerado ou reutilizado.
- **Banco de Dados Dedicado para S2**: A execução de S2 utiliza um arquivo SQLite exclusivo: `data/finbot_testnet_soak_s2.sqlite3`.
- **Modo Supervisionado**: O S2 inicial é executado em terminal interativo com acompanhamento do operador, e NÃO via Task Scheduler ou serviço em segundo plano não supervisionado.
- **Inviolabilidade de Produção**: `PRODUCTION_ORDERS_SENT = 0`, `PRODUCTION_WRITE_ENABLED = NO`.
- **Zero Push Automático por IA**: Qualquer envio de código do Notebook para o repositório remoto via `git push origin main` é prerrogativa exclusiva e autorizada pelo operador humano.

### 18.2 Passo a Passo do Deploy e Execução no PC Forte

#### Passo 1: Transferência e Atualização do Código (No PC Forte)
No PC Forte (`C:\Projetos\FinBot`), assegure que o repositório esteja sincronizado com o branch `main`:
```powershell
cd C:\Projetos\FinBot
git status
git pull origin main
```

#### Passo 2: Verificação do Ambiente Virtual e Instalação Editável
Garanta que as dependências estejam atualizadas no ambiente virtual oficial:
```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
```
*Critério: Todos os testes automatizados devem passar com 100% de sucesso antes de qualquer execução.*

#### Passo 3: Verificação de Credenciais Spot Testnet
Verifique se as credenciais da Binance Spot Testnet estão cadastradas no Windows Credential Manager:
```powershell
.\.venv\Scripts\python.exe -m finbot.credentials status --env spot_testnet
```
Se estiverem ausentes, cadastre com segurança via GUI local:
```powershell
.\.venv\Scripts\python.exe -m finbot.credentials_gui --env spot_testnet
```
*(Target canônico: `FinBot/Binance/SpotTestnet`)*

#### Passo 4: Executar Preflight Check na Testnet
Verifique a conectividade privada autenticada, leitura de saldos, integridade de mercado e barreiras de segurança:
```powershell
.\.venv\Scripts\python.exe -m finbot.testnet_preflight
```
*Critério: Todas as verificações privadas/públicas devem retornar `PASS`, com `TESTNET_ORDERS_SENT = 0`, `PRODUCTION_ORDERS_SENT = 0`, `PRODUCTION_WRITE_ENABLED = NO` e a linha final atestando `READY_FOR_TESTNET_ORDER = YES`.*

#### Passo 5: Executar Preview READ-ONLY com Banco S2
Execute uma verificação prévia do soak apontando para o banco dedicado do S2:
```powershell
.\.venv\Scripts\python.exe -m finbot.testnet_soak --db-path data/finbot_testnet_soak_s2.sqlite3
```
*Garantia: O comando opera por padrão em PREVIEW Safe Mode (sem `--confirm-testnet-soak`) e atesta `TESTNET_WRITE_EXECUTED = NO`.*

#### Passo 6: Executar Smoke Test ARMADO de um Único Ciclo (--once) com Banco S2
Execute o smoke test armado de um único ciclo pontual para validar a criação e migração automática do banco `finbot_testnet_soak_s2.sqlite3`:
```powershell
.\.venv\Scripts\python.exe -m finbot.testnet_soak --confirm-testnet-soak --once --db-path data/finbot_testnet_soak_s2.sqlite3
```
*Atenção: O comando armado com as flags `--confirm-testnet-soak --once` executa exatamente 1 ciclo na exchange. Pode enviar ordem somente à Binance Spot Testnet se houver sinal operacional (`BUY` ou `SELL`). Production permanece estritamente bloqueada (`PRODUCTION_ORDERS_SENT = 0`, `PRODUCTION_WRITE_ENABLED = NO`).*

#### Passo 7: Inspecionar Relatório de Status do Banco S2
Verifique o estado inicial e a saúde do runner no banco S2:
```powershell
.\.venv\Scripts\python.exe -m finbot.testnet_soak_status --db-path data/finbot_testnet_soak_s2.sqlite3
```

#### Passo 8: Início da Bateria Contínua Supervisionada (24 Horas)
Após a confirmação pelo operador, inicie a execução contínua supervisionada usando a flag `--confirm-testnet-soak` (SEM a flag `--once`):
```powershell
.\.venv\Scripts\python.exe -m finbot.testnet_soak --confirm-testnet-soak --db-path data/finbot_testnet_soak_s2.sqlite3
```
*Durante a execução:*
- **Semântica do Comando**: A presença de `--confirm-testnet-soak` sem a flag `--once` aciona o loop contínuo do runner (`run_testnet_soak_continuous`);
- **Intervalo do Ciclo**: O runner opera internamente em intervalo periódico fixo de 60 segundos por ciclo (`cycle_interval_seconds = 60.0`);
- O runner executa a reconciliação pré-ciclo antes de cada decisão de estratégia;
- Emite heartbeat dinâmico a cada ciclo, atualizando `runner_status = RUNNING`;
- Calcula taxas realistas (segregação exchange vs fallback estimado de 0.10%);
- Monitora slippage em USDT e bps em cada fill sem dupla contagem;
- Em caso de anomalia, o Circuit Breaker desarma o envio de novas ordens automaticamente;
- Production permanece categoricamente inviolada e bloqueada (`PRODUCTION_ORDERS_SENT = 0`, `PRODUCTION_WRITE_ENABLED = NO`).

#### Passo 9: Monitoramento Concorrente de Status (Em outro terminal no PC Forte)
O operador pode acompanhar o progresso em tempo real a qualquer momento sem interromper o processo:
```powershell
cd C:\Projetos\FinBot
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\python.exe -m finbot.testnet_soak_status --db-path data/finbot_testnet_soak_s2.sqlite3
```

#### Passo 10: Encerramento Gracioso (Graceful Shutdown)
Ao final das 24 horas (ou se necessária pausa técnica supervisionada), encerre o processo pressionando:
```text
Ctrl + C
```
*Comportamento do Graceful Shutdown*:
1. Captura o sinal de interrupção com segurança;
2. Conclui com integridade as tarefas em andamento;
3. Atualiza `runner_status = "STOPPED"` e grava `shutdown_at` no banco SQLite;
4. Preserva ordens UNKNOWN (se houver) para reconciliação futura;
5. Fecha a conexão com o banco de dados SQLite sem corrupção;
6. Nenhuma nova ordem é enviada.
