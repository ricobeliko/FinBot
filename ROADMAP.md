# FinBot — Roadmap de Desenvolvimento

Este documento descreve as etapas de evolução sequencial do FinBot. Cada fase deve estar completamente testada, validada e funcional antes de a próxima iniciar.

> **Aviso Importante**: Não implementar nenhuma fase antecipadamente. Atualmente a **FASE 5** está concluída.

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
