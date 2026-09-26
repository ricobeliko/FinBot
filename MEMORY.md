# FinBot Memory

## Estado atual
FASE 3 — Strategy Engine concluída.

### Implementado
- Signal BUY/SELL/HOLD (`strategy.py`)
- estratégia determinística SMA crossover (short=5, long=10)
- cálculo puramente matemático na Standard Library (sem pandas/numpy)
- detecção de evento de cruzamento (comparação de candle anterior vs atual)
- testes unitários determinísticos isolados (`test_strategy.py`)
- orquestração no `main.py` com carregamento de 20 candles

### Trading
disabled

### Orders
inexistentes

### API credentials
nenhuma

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
- CCXT adotado (camada de mercado/exchange)
- Backtesting.py futuramente (estudos históricos)
- SQLite futuramente (persistência local)
- Streamlit possivelmente futuramente (dashboard local)

## Estado financeiro
- nenhuma conta autenticada
- nenhuma API key / secret
- nenhum saldo privado consultado
- nenhuma ordem criada ou executada
- nenhum paper trade
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

## Último checkpoint
Strategy Engine funcional (FASE 3): cálculo determinístico de sinais BUY/SELL/HOLD via SMA Crossover, cobertura de testes unitários, isolado de rede e com trading disabled.

## Próxima fase
FASE 4 — Backtesting (dados históricos, métricas de performance e comparação com benchmark).
