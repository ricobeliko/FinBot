# FinBot Memory

## Estado atual
FASE 0 — Foundation

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
Fundação inicial (FASE 0): estrutura de pastas, documentação e aplicação mínima criadas; .venv ignorada no Git.

## Próxima fase
FASE 1 — validar aplicação Python mínima (configuração, logging básico, execução central).
