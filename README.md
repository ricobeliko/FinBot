# FinBot

Bot local para estudo, validação e automação de estratégias de negociação de ativos e criptoativos.

---

## STATUS ATUAL

```text
STATUS ATUAL:
Foundation only.
No trading functionality exists.
```

O projeto está na **FASE 0 (Foundation)**. Apenas a estrutura básica de diretórios, regras operacionais para IA e ponto de entrada mínimo estão configurados. Nenhuma exchange, rede externa, banco de dados ou estratégia está conectada.

---

## Objetivo

Fornecer uma plataforma local-first, enxuta, determinística e segura para testes quantitativos e execução controlada de estratégias financeiras, sem complexidades de nuvem ou microserviços.

---

## Arquitetura Planejada

```text
Market Data ──▶ Strategy ──▶ Risk Manager ──▶ Broker ──▶ Storage
```

- **Local-first**: Execução local no Windows.
- **Segurança de Fluxo**: A estratégia nunca se comunica diretamente com a exchange; toda ordem passa pelo `Risk Manager`.
- **Modos Futuros**: `MONITOR`, `BACKTEST`, `PAPER` e `LIVE` (bloqueado por padrão).

---

## Requisitos

- Windows
- Python 3.12 (>=3.12,<3.13)
- Git (apenas local)

---

## Instalação e Execução Local

1. Navegar até o diretório:
   ```powershell
   cd D:\Projetos\FinBot
   ```

2. Ativar o ambiente virtual:
   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```

3. Instalar o projeto localmente em modo editável:
   ```powershell
   python -m pip install -e .
   ```

4. Executar a aplicação mínima:
   ```powershell
   python -m finbot.main
   ```

   Saída esperada:
   ```text
   FinBot
   Status: Foundation
   Trading: disabled
   ```

---

## Roadmap Resumido

- **FASE 0 — Foundation** (atual): Estrutura base, documentação e aplicação mínima.
- **FASE 1 — Python Core**: Configuração e logging.
- **FASE 2 — Market Monitor**: Integração CCXT somente leitura de dados públicos.
- **FASE 3 — Strategy Engine**: Motor de sinais determinísticos.
- **FASE 4 — Backtesting**: Testes históricos e métricas offline.
- **FASE 5 — Paper Trading**: Simulação de ordens e carteira virtual com SQLite.
- **FASE 6 — Risk Engine**: Limites, validações e kill switch.
- **FASE 7 — Dashboard Local**: Acompanhamento visual via localhost.
- **FASE 8 — Integração Live**: Operações reais (bloqueado por padrão).
- **FASE 9 — Estabilidade**: Resiliência e recuperação de conexões.
- **FASE 10 — Empacotamento/Transferência**: Preparação final para PC de destino.

Consulte `ROADMAP.md` para o detalhamento completo.
