# FinBot Memory

## Estado atual
FASE 1 — Python Core concluída.

### Implementado
- configuração local mínima (`config.py`)
- logging local em console e arquivo (`logging_setup.py`)
- startup previsível com exibição de ambiente e modo
- shutdown limpo

### Trading
disabled

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
- CCXT futuramente (camada de mercado/exchange)
- Backtesting.py futuramente (estudos históricos)
- SQLite futuramente (persistência local)
- Streamlit possivelmente futuramente (dashboard local)

## Estado financeiro
- nenhuma exchange conectada
- nenhuma API key
- nenhum paper trade
- nenhum live trade
- nenhum dinheiro real envolvido

## Decisões relevantes
- D001: Python 3.12 adotado como versão padrão.
- D002: Git exclusivamente local na fase inicial.
- D003: Arquitetura Local-first (sem cloud, sem serviços remotos).
- D004: Simplicidade acima de arquitetura sofisticada.
- D005: CCXT planejado para integração com exchanges.
- D006: SQLite planejado para armazenamento local.
- D007: IA não toma decisões financeiras (regras determinísticas).
- D008: Live Trading estritamente bloqueado por padrão.

## Último checkpoint
Python Core funcional (FASE 1): configuração local mínima, logging em console/arquivo, ciclo de vida previsível e saída limpa.

## Próxima fase
FASE 2 — Market Monitor (CCXT, dados públicos, nenhum trade).
