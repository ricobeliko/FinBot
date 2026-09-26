# FinBot — Runbook Operacional

Procedimentos operacionais básicos e diretos para o ambiente local.

---

## 1. Navegar até o Projeto

```powershell
cd D:\Projetos\FinBot
```

---

## 2. Ativar Ambiente Virtual

No PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

---

## 3. Verificar Ambiente e Ferramentas

```powershell
python --version
pip --version
git status
```

---

## 4. Instalar Projeto Localmente em Modo Editável

```powershell
python -m pip install -e .
```

---

## 5. Executar Market Monitor (FASE 2 / 3)

Com o ambiente ativado:

```powershell
python -m finbot.main
```

Consulta dados públicos de ticker e 20 candles de 1m na Binance Spot (BTC/USDT) e calcula o sinal operacional determinístico (`BUY`, `SELL`, `HOLD`) por cruzamento de médias (SMA 5 / SMA 10). Os registros são exibidos no console e gravados em `logs/finbot.log`.

---

## 6. Executar Backtesting Reproduzível (FASE 4)

Com o ambiente ativado:

```powershell
python -m finbot.backtest
```

Executa a simulação histórica reproduzível da estratégia SMA Crossover sobre o snapshot local salvo em `data/backtest/binance_BTCUSDT_5m.json` (500 candles de 5m da Binance Spot). Exibe relatório no terminal com retorno da estratégia, Buy & Hold, trades, taxa de acerto (win rate), drawdown máximo e profit factor.

Para forçar atualização/novo download do snapshot histórico:
```powershell
python -m finbot.backtest --refresh
```

---

## 7. Executar Testes Unitários

```powershell
python -m unittest discover tests
```

Executa toda a bateria de testes unitários determinísticos (sem conexão de internet e sem dados privados).

---

## 8. Validar Compilação do Código

```powershell
python -m compileall src
```

