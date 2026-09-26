# FinBot Memory

## Estado atual
FASE 6 — Risk Engine concluída.

### Implementado
- motor de risco determinístico desacoplado (`src/finbot/risk.py`) como barreira obrigatória entre estratégia e execução
- fluxo estrito: Market Data -> Strategy -> Signal -> Risk Engine -> Paper Broker -> SQLite
- proteções paper implementadas:
  - max position (100.00 USDT e limite de 1 posição spot simultânea)
  - daily loss limit (bloqueio de BUY ao atingir 50.00 USDT de prejuízo realizado no dia UTC)
  - stop loss defensivo (encerramento imediato da posição com 2.0% de desvalorização, gerando exit_reason="STOP_LOSS")
  - cooldown defensivo (1 candle fechado de intervalo obrigatório após fechar posição)
  - kill switch local persistente no SQLite com controle CLI (`--kill-switch on/off`)
- inviolabilidade de saídas: ordens SELL para redução ou encerramento de risco nunca são bloqueadas por limites de perda, cooldown ou kill switch
- migração idempotente de schema SQLite mantendo integridade de bases existentes (`exit_reason` em `paper_trades`)
- comandos CLI para ciclo, consulta offline expandida (`--status`) e reset seguro (`--reset --yes`)
- zero dependências externas adicionais (apenas Standard Library: `Decimal`, `sqlite3`, `dataclasses`, `enum`, `datetime`)
- 51 testes unitários automatizados passando sem acesso à rede (`test_risk.py`, `test_paper.py`, `test_backtest.py`, `test_strategy.py`, `test_exchange.py`)

### Proteções paper
- max position
- daily loss
- stop loss
- cooldown
- kill switch

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
- SQLite adotado (persistência local de paper trading e estados de risco)
- Streamlit possivelmente futuramente (dashboard visual local)

## Estado financeiro
- nenhuma conta autenticada
- nenhuma API key / secret
- nenhum saldo privado consultado
- nenhuma ordem real criada ou executada
- paper trading ativo com capital fictício e controle estrito de risco
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
- D012: Risk Engine Determinístico e Local (D012).

## Último checkpoint
Risk Engine determinístico operacional (FASE 6): interposição obrigatória entre estratégia e Paper Broker, stop loss defensivo de 2.0%, limite de perda diária de 50 USDT, cooldown de 1 candle fechado, kill switch persistente com CLI, 51 testes passando e zero chamadas privadas a exchanges.

## Próxima fase
FASE 7 — Dashboard visual local.
