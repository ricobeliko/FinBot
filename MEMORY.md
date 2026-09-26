# FinBot Memory

## Estado atual
FASE 4 — Backtesting concluída.

### Implementado
- dataset histórico local em `data/backtest/` com metadados completos
- backtesting reproduzível via entrada CLI dedicada (`python -m finbot.backtest`)
- estratégia SMA existente reutilizada sem duplicação (`FinBotSMAStrategy` adapta `evaluate_sma_crossover`)
- simulação spot long-only (sem short, sem alavancagem, sem futuros, sem margem)
- custos configuráveis (capital inicial 10000.0 USDT, comissão 0.10% simulação)
- prevenção comprovada de look-ahead (execução no Open da próxima barra)
- métricas básicas e comparação direta com Buy & Hold
- testes unitários com dados sintéticos e cobertura ampla (`test_backtest.py`)

### Trading
disabled (SIMULATION ONLY)

### Orders
inexistentes (nenhuma ordem enviada a exchanges)

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
- CCXT adotado (dados públicos de mercado)
- Backtesting.py 0.6.6 adotado (simulação e estudos históricos locais)
- SQLite futuramente (persistência local)
- Streamlit possivelmente futuramente (dashboard local)

## Estado financeiro
- nenhuma conta autenticada
- nenhuma API key / secret
- nenhum saldo privado consultado
- nenhuma ordem real criada ou executada
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
- D010: Adoção de Backtesting.py para Simulação Histórica Local (AGPL-3.0+).

## Último checkpoint
Backtesting reproduzível funcional (FASE 4): simulação offline de SMA Crossover sobre snapshot local de 500 candles 5m BTC/USDT, métricas apuradas, sem look-ahead, 20 testes unitários passando e trading real inexistente.

## Próxima fase
FASE 5 — Paper Trading (simulação de carteira virtual em tempo real com persistência SQLite).
