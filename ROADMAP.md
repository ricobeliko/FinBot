# FinBot — Roadmap de Desenvolvimento

Este documento descreve as etapas de evolução sequencial do FinBot. Cada fase deve estar completamente testada, validada e funcional antes de a próxima iniciar.

> **Aviso Importante**: Não implementar nenhuma fase antecipadamente. Atualmente a **FASE 7.5** está concluída.

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

### NEXT — Paper Soak Test (Planejada)
- Observação contínua do Automated Paper Runner por múltiplos dias consecutivos no Windows
- Monitoramento de reconexões, reinicializações e estabilidade do SQLite (file locks)
- Avaliação de sinais, preenchimentos simulados, stop loss, cooldown e comportamento do kill switch
- Validação de estabilidade 24/7 sem vazamento de memória ou instâncias órfãs

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
- Conexão com API autenticada de exchange
- Uso exclusivo de chaves de API sem permissão de saque (*no withdrawal*)
- Modo Live bloqueado por padrão; liberação com dupla confirmação operacional

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
