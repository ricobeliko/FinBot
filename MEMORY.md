# FinBot Memory

## Estado atual
FASE 7.5 — Automated Paper Runner concluída.

### Implementado
- scripts operacionais em `scripts/` (`run_paper.ps1`, `run_dashboard.ps1`, `check_finbot.ps1`, `install_paper_task.ps1`, `remove_paper_task.ps1`)
- automação periódica do Paper Trading (1m) via Windows Task Scheduler sem loops ou daemon permanente
- política estrita contra sobreposição de instâncias (`MultipleInstances: IgnoreNew`) e timeout de 5 minutos
- observabilidade de ciclo persistida no SQLite (`last_cycle_timestamp`, `last_successful_cycle_timestamp`, `last_cycle_result`, `last_cycle_message`)
- função determinística pura de frescor operacional (`calculate_runner_freshness`: `RECENT` vs `STALE`) no `metrics.py`
- card e badge de frescor do Paper Runner no dashboard Streamlit e exibição detalhada no CLI (`--status`)
- logging estruturado e diagnóstico para cada ciclo executado no console e `logs/finbot.log`
- 66 testes unitários automatizados passando (`test_runner.py`, `test_metrics.py`, `test_risk.py`, `test_paper.py`, `test_backtest.py`, `test_strategy.py`, `test_exchange.py`)

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
- Git somente local
- branch: main
- sem remote

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

## Último checkpoint
Automated Paper Runner homologado (FASE 7.5): orquestração periódica a cada 1m via Windows Task Scheduler com política IgnoreNew, scripts PowerShell em scripts/, observabilidade persistente no SQLite, status RECENT/STALE no dashboard e CLI, 66 testes passando e zero daemon complexo.

## Próxima etapa (NEXT)
Paper Soak Test — Período de observação contínua de múltiplos dias para validação de estabilidade, concorrência, reconexões e consistência do SQLite.
