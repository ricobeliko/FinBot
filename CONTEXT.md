# FinBot — Contexto do Projeto

## Visão Geral

O **FinBot** é um bot de execução local projetado para estudo, validação e automação de estratégias de negociação de ativos e criptoativos.

- **Ambiente de Desenvolvimento**: Notebook atual (Windows).
- **Ambiente de Execução Final**: Outro computador pessoal (Windows), rodando localmente de forma contínua e autônoma.
- **Topologia**: 100% Local-first. Sem microserviços, sem dependência de nuvem, sem Docker e sem complexidades de orquestração externa.

---

## Fluxo e Arquitetura Pretendida

O sistema é concebido como um pipeline sequencial e desacoplado:

```text
Market Data  ──▶  Strategy  ──▶  Risk Manager  ──▶  Broker  ──▶  Storage
```

### Regra Cardinal de Fluxo de Ordens

**A estratégia NUNCA conversa diretamente com a exchange.**

O fluxo estrito de envio de ordens é:

```text
Strategy
   │
   ▼
Risk Manager (validação de limites, exposição e integridade)
   │
   ▼
Broker (camada de execução / abstração de ordens)
   │
   ▼
Exchange (API externa via CCXT)
```

Qualquer tentativa de envio direto ou desvio do `Risk Manager` é expressamente proibida pela arquitetura.

---

## Modos de Operação Futuros

O sistema suportará quatro modos de operação:

1. **MONITOR**: Coleta e observação de dados públicos de mercado em tempo real. Nenhum trade e nenhuma emissão de ordens.
2. **BACKTEST**: Simulação de estratégias contra bases históricas locais para avaliação de métricas e risco.
3. **PAPER**: Simulação de negociação em tempo real com carteira e saldo virtuais, registrando execuções simuladas em banco SQLite local.
4. **LIVE**: Execução de ordens reais em exchange com capital financeiro real.

> **Importante**: O modo **LIVE** é bloqueado por padrão arquitetural e de configuração. Sua implementação e liberação ocorrerão estritamente em fase avançada e sob autorização explícita do operador.
