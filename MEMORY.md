# FinBot Memory

## Estado atual
FASE 2 — Market Monitor concluída.

### Implementado
- CCXT integrado para dados públicos de mercado
- market data público (`exchange.py`)
- BTC/USDT como par de validação inicial
- consulta e exibição de ticker público (last, bid, ask, timestamp)
- consulta de candles públicos (OHLCV, 1m) com rate limit ativado
- tratamento de erros operacionais (`ExchangeError`, BadSymbol, NetworkError)

### Trading
disabled

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

## Último checkpoint
Market Monitor funcional (FASE 2): consulta pública de ticker e candles via CCXT (Binance Spot, BTC/USDT), rate limit ativo, sem credenciais e trading disabled.

## Próxima fase
FASE 3 — Strategy Engine (sinais determinísticos BUY/SELL/HOLD sem ordens reais).
