# FinBot Memory

## Estado atual
FASE 5 — Paper Trading concluída.

### Implementado
- carteira simulada local com persistência SQLite (`data/finbot_paper.sqlite3` via `storage.py`)
- simulação forward testing em tempo real com capital fictício (`python -m finbot.paper`)
- modelo Spot LONG exclusivo (uma posição aberta por vez, notional técnico de 100 USDT)
- comissão simulada de 0.10% em entradas e saídas
- filtragem temporal de candles incompletos (apenas candles fechados são avaliados)
- deduplicação estrita via timestamp do último candle fechado processado
- comandos CLI para execução de ciclo, consulta offline (`--status`) e reset seguro (`--reset --yes`)
- transações atômicas no SQLite com garantia de rollback
- 34 testes unitários automatizados passando (`test_paper.py`, `test_backtest.py`, `test_strategy.py`, `test_exchange.py`)

### Market
real/public

### Money
fictício/local (10000.00 USDT inicial)

### Real trading
disabled (nenhuma ordem enviada a exchanges)

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
- CCXT adotado (dados públicos de mercado)
- Backtesting.py 0.6.6 adotado (simulação e estudos históricos locais)
- SQLite adotado (persistência local de paper trading)
- Streamlit possivelmente futuramente (dashboard local)

## Estado financeiro
- nenhuma conta autenticada
- nenhuma API key / secret
- nenhum saldo privado consultado
- nenhuma ordem real criada ou executada
- paper trading ativo com capital fictício
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

## Último checkpoint
Paper Trading funcional e persistente (FASE 5): forward testing sobre dados públicos da Binance Spot com saldo fictício de 10000 USDT, deduplicação de candles, suporte a --status e --reset, 34 testes unitários passando e trading real inexistente.

## Próxima fase
FASE 6 — Risk Engine (dimensionamento de posição, limites estritos de perda e kill switch).
