# FinBot

Bot local para estudo, validação e automação de estratégias de negociação de ativos e criptoativos.

---

## STATUS ATUAL

```text
STATUS ATUAL:
FASE 3 — Strategy Engine.
No trading functionality exists.
```

O projeto concluiu a **FASE 3 (Strategy Engine)**. Possui consulta a dados públicos de mercado via CCXT (Binance Spot, BTC/USDT) e cálculo determinístico de sinais operacionais (`BUY`, `SELL`, `HOLD`) por cruzamento de médias móveis simples (SMA 5 / SMA 10) sobre histórico recente de candles.

> **Importante**: Sinais são puramente informativos e matemáticos. Nenhuma ordem, carteira, saldo ou funcionalidade de trading existe.

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

3. Instalar o projeto localmente em modo editável com dependências:
   ```powershell
   python -m pip install -e .
   ```

4. Executar a aplicação:
   ```powershell
   python -m finbot.main
   ```

   Saída esperada:
   ```text
   FinBot
   Environment: local
   Trading mode: disabled
   Status: running

   Exchange: binance
   Symbol: BTC/USDT

   Last price: <valor_atual>
   Candles loaded: 20

   Strategy:
   SMA 5 / SMA 10

   Short MA: <valor_curto>
   Long MA: <valor_longo>

   Signal: HOLD (ou BUY / SELL conforme o mercado)
   Reason: <motivo_do_sinal>

   Trading: disabled
   ```

---

## Roadmap Resumido

- **FASE 0 — Foundation** (concluída): Estrutura base, documentação e aplicação mínima.
- **FASE 1 — Python Core** (concluída): Configuração local e logging básico.
- **FASE 2 — Market Monitor** (concluída): Integração CCXT somente leitura de dados públicos.
- **FASE 3 — Strategy Engine** (concluída): Motor de sinais determinísticos (SMA Crossover).
- **FASE 4 — Backtesting**: Testes históricos e métricas offline.
- **FASE 5 — Paper Trading**: Simulação de ordens e carteira virtual com SQLite.
- **FASE 6 — Risk Engine**: Limites, validações e kill switch.
- **FASE 7 — Dashboard Local**: Acompanhamento visual via localhost.
- **FASE 8 — Integração Live**: Operações reais (bloqueado por padrão).
- **FASE 9 — Estabilidade**: Resiliência e recuperação de conexões.
- **FASE 10 — Empacotamento/Transferência**: Preparação final para PC de destino.

Consulte `ROADMAP.md` para o detalhamento completo.
