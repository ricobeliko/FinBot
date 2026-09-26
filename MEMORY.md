# FinBot Memory

## Estado atual
FASE 7 — Dashboard visual local concluída.

### Implementado
- dashboard visual local com Streamlit (`src/finbot/dashboard.py`)
- módulo de métricas desacopladas e puras (`src/finbot/metrics.py`)
- visualização em tempo real de saldo paper, patrimônio estimado, posição, P/L realizado e não realizado
- gráfico de evolução cumulativa do P/L realizado por trade fechado
- histórico recente dos últimos 50 trades com motivos de saída (`exit_reason`)
- painel de controle e monitoramento do Risk Engine (Kill Switch, Daily Loss, Max Position, Cooldown e último bloqueio)
- status operacional do bot com último candle fechado e último sinal avaliado
- layout responsivo adaptável para desktop e smartphones
- fallback gracioso para funcionamento 100% offline se conexão de internet estiver indisponível
- 58 testes unitários automatizados passando (`test_metrics.py`, `test_risk.py`, `test_paper.py`, `test_backtest.py`, `test_strategy.py`, `test_exchange.py`)

### Dashboard
local
read only
responsive
localhost

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

## Último checkpoint
Dashboard visual local homologado (FASE 7): interface Streamlit em localhost:8501, 100% read-only, métricas de patrimônio, P/L, trades recentes, monitoramento de risco e gráficos reais, 58 testes passando e zero acesso remoto.

## Próxima fase
FASE 7B / preparação para operação contínua e futura visualização mobile.
