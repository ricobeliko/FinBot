# FinBot — Roadmap de Desenvolvimento

Este documento descreve as etapas de evolução sequencial do FinBot. Cada fase deve estar completamente testada, validada e funcional antes de a próxima iniciar.

> **Aviso Importante**: Não implementar nenhuma fase antecipadamente. Atualmente a **FASE 1** está concluída.

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

### FASE 2 — Market Monitor
- Integração da biblioteca CCXT
- Conexão e coleta de dados públicos de mercado (tickers, orderbook, candles)
- Operação estritamente em modo leitura; nenhum trade ou ordem

---

### FASE 3 — Strategy Engine
- Mecanismo determinístico de sinais (`BUY`, `SELL`, `HOLD`)
- Avaliação de regras matemáticas e indicadores técnicos
- Nenhuma emissão de ordens reais

---

### FASE 4 — Backtesting
- Ingestão e processamento de bases históricas
- Simulação offline de performance e métricas (drawdown, Sharpe, win rate)
- Comparação com benchmarks simples (Buy & Hold)

---

### FASE 5 — Paper Trading
- Simulação de carteira com saldo fictício em tempo real
- Execução simulada de ordens com cálculo de slippage e taxas estimadas
- Persistência das operações em banco local SQLite

---

### FASE 6 — Risk Engine
- Definição e aplicação de limites estritos (tamanho máximo de posição, perda máxima diária)
- Mecanismo de parada de emergência (*Kill Switch*)
- Validações de integridade contra ordens incorretas ou duplicadas

---

### FASE 7 — Dashboard Local
- Interface visual interativa para acompanhamento (provavelmente Streamlit)
- Execução estritamente em `localhost`
- Gráficos de saldo, posições abertas, histórico de sinais e métricas de risco

---

### FASE 8 — Integração Live
- Conexão com API autenticada de exchange
- Uso exclusivo de chaves de API sem permissão de saque (*no withdrawal*)
- Modo Live bloqueado por padrão; liberação com dupla confirmação operacional

---

### FASE 9 — Estabilidade e Resiliência
- Tratamento avançado de desconexões de rede e falhas de socket/HTTP
- Mecanismos de reinício automático e recuperação de estado consistente
- Alarmes e logs detalhados de anomalias operacionais

---

### FASE 10 — Empacotamento e Transferência
- Preparação para migração ao PC definitivo de execução (Windows)
- Scripts de instalação e provisionamento do ambiente
- Scripts de inicialização automática e monitoramento de processo em segundo plano
