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

## 7. Executar Paper Trading com Risk Engine (FASE 6)

Com o ambiente ativado:

Executa um ciclo one-shot de simulação em tempo real sobre dados públicos passando pela validação do Risk Engine:
```powershell
python -m finbot.paper
```

Consulta o saldo, posições, histórico e métricas de risco sem acessar a internet (offline):
```powershell
python -m finbot.paper --status
# ou com foco em telemetria do soak test:
python -m finbot.paper --soak-status
```

Ativa o Kill Switch localmente (bloqueia novos BUYs mantendo permissão de saída):
```powershell
python -m finbot.paper --kill-switch on
```

Desativa o Kill Switch localmente (restaura operação normal):
```powershell
python -m finbot.paper --kill-switch off
```

Restaura o saldo inicial fictício (10000.00 USDT), zera as operações simuladas e limpa o estado de risco e telemetria:
```powershell
python -m finbot.paper --reset --yes
```

---

## 8. Executar Dashboard Visual Local (FASE 7)

Com o ambiente ativado:

```powershell
streamlit run src/finbot/dashboard.py --server.address=127.0.0.1
# ou via script operacional:
powershell -ExecutionPolicy Bypass -File scripts\run_dashboard.ps1
```

Inicia o dashboard visual local em `http://127.0.0.1:8501`.
- **Modo**: 100% Read-Only (visualização de patrimônio, posições, P/L, trades, Risk Engine, Runner Health e frescor do Paper Runner).
- **Rede**: Estritamente local (`127.0.0.1`), sem exposição para rede externa ou internet.
- **Resiliência Offline**: Se a internet estiver indisponível, o painel carrega todos os dados locais do SQLite normalmente.
- **Encerramento**: Pressione `Ctrl + C` no terminal para parar o servidor Streamlit.

---

## 9. Scripts Operacionais e Automação (FASE 7.5 / 7.6)

### 9.1 Diagnóstico de Integridade Local
```powershell
powershell -ExecutionPolicy Bypass -File scripts\check_finbot.ps1
```
Valida Python, virtualenv, SQLite, status do Paper Trading, ausência de remotes Git e status detalhado da tarefa agendada no Windows.

### 9.2 Execução de Ciclo Individual One-Shot
```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_paper.ps1
```
Invoca `finbot.paper` utilizando o Python da `.venv` sem abrir shell interativo e preservando o código de saída.

### 9.3 Instalar Tarefa Agendada no Windows Task Scheduler
```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_paper_task.ps1
```
Registra a tarefa `FinBot Paper Runner` para o usuário local, com periodicidade de 1 minuto, política anti-concorrência `IgnoreNew` e timeout de 5 minutos.

### 9.4 Remover Tarefa Agendada do Windows Task Scheduler
```powershell
powershell -ExecutionPolicy Bypass -File scripts\remove_paper_task.ps1
```
Desregistra e remove com segurança a tarefa do agendador do Windows.

---

## 10. Executar Testes Unitários

```powershell
python -m unittest discover tests
```

Executa toda a bateria de testes unitários determinísticos (70 testes cobrindo Exchange, Strategy, Backtest, Storage, Risk Engine, Metrics, Automated Paper Runner, isolamento de rede e rotação de logs sem conexão de internet e sem dados privados).

---

## 11. Validar Compilação do Código

```powershell
python -m compileall src tests
```

---

## 12. Fluxo de Sincronização entre Notebook e PC Forte (GitHub Privado)

O repositório privado (`https://github.com/ricobeliko/FinBot.git`) é utilizado unicamente para backup e transferência de código, sem CI/CD ou automações na nuvem.

### 12.1 No Notebook (Desenvolvimento)
Após implementar e validar alterações locais:
```powershell
git status
git add .
git commit -m "mensagem descritiva"
git push origin main
```

### 12.2 No PC Forte (Testes Locais e Runtime 24/7)
Para receber novas atualizações e validar antes de executar:
```powershell
git pull origin main
python -m unittest discover tests
python -m finbot.backtest
powershell -ExecutionPolicy Bypass -File scripts\check_finbot.ps1
```

> **Nota Operacional**: O banco de dados operacional SQLite (`data/finbot_paper.sqlite3`), logs e eventuais arquivos `.env` são ignorados no Git e pertencem estritamente à máquina local em que o bot está executando.
