# FinBot Memory

## Estado atual
FASE 7.6 — Paper Soak Test em andamento (Preparação & Observabilidade concluídas).

### PAPER SOAK TEST STARTED
Data/hora UTC: 2026-09-27T00:11:58Z
Baseline:
- USDT: 10000.00
- BTC: 0.00000000
- Posição: NONE
- Trades: 0
- Kill Switch: INACTIVE
- Runner Freshness: RECENT
Objetivo inicial: 72 horas

### Implementado
- telemetria enxuta e atômica persistida em `paper_state` (`soak_start_timestamp`, `total_cycles`, `successful_cycles`, `failed_cycles`, `deduplicated_cycles`, `last_error`, `last_error_timestamp`)
- isolamento estrito de falhas de rede: erros transitórios registram falha na telemetria sem jamais alterar saldo, posição ou trades
- CLI estendido com `--soak-status` (e `--status` aprimorado) exibindo métricas do soak test e diagnóstico de erros
- painel do dashboard estendido com seção de Runner Health (início do soak, contadores e alerta de último erro)
- rotação automática de logs (`RotatingFileHandler`: 5 MB, 3 backups) via Standard Library em `logs/finbot.log`
- script de diagnóstico `scripts/check_finbot.ps1` enriquecido com estado detalhado da tarefa agendada do Windows
- 70 testes unitários automatizados determinísticos passando sem internet
- tarefa Windows `FinBot Paper Runner` ativa e operando a cada 1 minuto (IgnoreNew)

### Dashboard
local
read only
responsive
localhost

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
- projeto: D:\Projetos\FinBot
- ambiente virtual: .venv
- Git: repositório GitHub privado configurado (backup e sincronização sem CI/CD)
  - Notebook: máquina de desenvolvimento, escrita de código, commits e push
  - PC forte: clone/pull, testes locais completos, Paper Runner, Dashboard e runtime 24/7
- branch: main
- remote: origin (https://github.com/ricobeliko/FinBot.git)

## Arquitetura pretendida
- Python 3.12
- CCXT 4.5.84 adotado (dados públicos de mercado)
- Backtesting.py 0.6.6 adotado (simulação e estudos históricos locais)
- SQLite adotado (persistência local de paper trading e estados de risco)
- Streamlit 1.64.0 adotado (dashboard visual local e responsivo)
- Windows Task Scheduler (orquestração periódica externa one-shot)

## Estado financeiro
- nenhuma conta autenticada
- nenhuma API key / secret
- nenhum saldo privado consultado
- nenhuma ordem real criada ou executada
- paper trading ativo com capital fictício e controle estrito de risco
- dashboard 100% read-only sem capacidade de envio de ordens
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

## Último checkpoint
Paper Soak Test iniciado e telemetria operacional homologada (FASE 7.6): telemetria atômica em SQLite `paper_state`, rotação de logs (5MB, 3 backups), isolamento de falhas de rede, CLI `--soak-status`, runner health no dashboard, 70 testes passando e tarefa agendada Windows ativa e executando a cada 1m.

## Próxima etapa (NEXT)
Acompanhamento contínuo da janela de 72 horas do Paper Soak Test antes de qualquer evolução para FASE 7B ou posteriores.
