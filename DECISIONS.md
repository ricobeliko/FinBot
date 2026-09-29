# FinBot — Registro de Decisões de Arquitetura (ADRs)

Este documento registra de forma simplificada as decisões arquiteturais tomadas no projeto FinBot, seus contextos e justificativas.

---

### D001 — Adoção de Python 3.12
- **Status**: Aceito
- **Data**: FASE 0
- **Contexto**: Escolha da versão base da linguagem para desenvolvimento do bot.
- **Decisão**: Utilizar Python 3.12 (especificamente 3.12.10 disponível no ambiente).
- **Motivo**: Excelente equilíbrio entre estabilidade, alto desempenho nas versões recentes do CPython, suporte pleno do ecossistema quantitativo/financeiro e ampla compatibilidade de bibliotecas.

---

### D002 — Repositório Git Exclusivamente Local Inicialmente
- **Status**: Aceito
- **Data**: FASE 0
- **Contexto**: Controle de versão e colaboração.
- **Decisão**: Manter o repositório Git apenas em ambiente local, sem configurar remotes ou repositórios públicos/privados no GitHub nesta etapa.
- **Motivo**: O usuário não deseja publicar o projeto durante o ciclo inicial de concepção e desenvolvimento.

---

### D003 — Arquitetura Local-first
- **Status**: Aceito
- **Data**: FASE 0
- **Contexto**: Modelo de implantação e hospedagem do bot.
- **Decisão**: O FinBot será executado integralmente em máquina local Windows, sem dependência de serviços cloud, containers Docker ou orquestradores remotos.
- **Motivo**: Reduz custos, simplifica manutenção, garante controle físico dos dados e privacidade operacional.

---

### D004 — Arquitetura Simples e Direta
- **Status**: Aceito
- **Data**: FASE 0
- **Contexto**: Filosofia de design de software.
- **Decisão**: Priorizar simplicidade sobre engenharia excessiva. Não criar microserviços, padrões complexos sem demanda imediata ou abstrações preventivas.
- **Motivo**: Evitar débito técnico de sobre-engenharia, manter facilidade de inspeção pelo operador e garantir que cada linha de código tenha função real demonstrável.

---

### D005 — CCXT como Camada Oficial de Exchange (Adotado)
- **Status**: Aceito (Adotado na FASE 2)
- **Data**: FASE 0 (Planejado) / FASE 2 (Adotado)
- **Contexto**: Acesso a dados públicos de mercado e APIs de exchanges de criptoativos.
- **Decisão**: Adotar a biblioteca CCXT como cliente unificado para consultas públicas de mercado e futuras integrações.
- **Motivo**: Biblioteca padrão da indústria, ativamente mantida, madura, e que oferece interface unificada para centenas de exchanges.

---

### D006 — SQLite Planejado para Armazenamento Local
- **Status**: Aceito (Planejado)
- **Data**: FASE 0
- **Contexto**: Persistência de configurações, trades em paper trading e histórico operacional.
- **Decisão**: Utilizar SQLite como banco de dados local a partir da FASE 5.
- **Motivo**: Banco embutido (zero configuração de servidor externo), transacional (ACID), leve, nativo no Python e altamente confiável para uso em um único processo.

---

### D007 — IA Não Toma Decisões Financeiras
- **Status**: Aceito
- **Data**: FASE 0
- **Contexto**: Aplicação de Inteligência Artificial no projeto.
- **Decisão**: A IA (agentes LLM) é empregada exclusivamente como ferramenta de desenvolvimento, testes e documentação. As estratégias de trading serão puramente determinísticas, baseadas em regras e indicadores objetivos.
- **Motivo**: Eliminar riscos de alucinação, comportamento imprevisível ou não-determinismo em decisões que envolvem risco financeiro.

---

### D008 — Live Trading Bloqueado por Padrão
- **Status**: Aceito
- **Data**: FASE 0
- **Contexto**: Segurança patrimonial e proteção operacional contra acidentes.
- **Decisão**: O envio de ordens reais com capital financeiro permanecerá desativado por padrão no código, exigindo configuração intencional e autorização explícita do operador em fase adequada.
- **Motivo**: Minimização drástica do risco operacional durante desenvolvimento, testes e simulações.

---

### D009 — Estratégia Determinística com Cruzamento de Médias (SMA Crossover)
- **Status**: Aceito
- **Data**: FASE 3
- **Contexto**: Implementação do primeiro motor de estratégia (Strategy Engine) para validação arquitetural.
- **Decisão**: Adotar a estratégia de cruzamento de médias móveis simples (SMA curta vs SMA longa) implementada exclusivamente com a Standard Library do Python, desacoplada de CCXT e de bibliotecas externas pesadas (sem pandas, numpy ou TA-Lib).
- **Motivo**: Determinismo estrito, cálculo matemático simples e transparente, facilidade de testes unitários isolados e preservação do princípio de não adicionar dependências desnecessárias.

---

### D010 — Adoção de Backtesting.py para Simulação Histórica Local
- **Status**: Aceito
- **Data**: FASE 4
- **Contexto**: Necessidade de validar o comportamento histórico e o desempenho da estratégia sobre dados reais de mercado de forma reproduzível e isolada de ordens reais.
- **Decisão**: Adotar a biblioteca `backtesting==0.6.6` (e `pandas==3.0.6` como dependência direta declarada) para execução de simulações locais através de `FractionalBacktest`, integrando o motor oficial `evaluate_sma_crossover` sem duplicar lógica.
- **Licença e Implicações**: A biblioteca Backtesting.py 0.6.6 é distribuída sob licença AGPL-3.0+. A dependência foi adotada nesta fase estritamente para backtesting e simulação local, mantendo o projeto integralmente privado e restrito ao ambiente local do operador. A licença e seus requisitos de compartilhamento de código-fonte devem ser formalmente reavaliados antes de qualquer eventual distribuição pública ou comercialização do projeto.
- **Motivo**: Ferramenta consolidada, de fácil integração com dados tabulares do pandas, semântica transparente de execução no próximo candle (mitigação intrínseca de look-ahead bias) e suporte comprovado a dimensionamento fracionado de contratos para criptoativos.

---

### D011 — Arquitetura de Paper Trading com Persistência SQLite Local
- **Status**: Aceito
- **Data**: FASE 5
- **Contexto**: Necessidade de executar forward testing em tempo real com capital fictício, persistindo saldos e ordens simuladas entre reinicializações sem conexão autenticada com a exchange.
- **Decisão**: Adotar a arquitetura de Paper Trading local com persistência via `sqlite3` da Python Standard Library (`storage.py` e `paper.py`):
  - Carteira simulada mantida integralmente em banco local (`data/finbot_paper.sqlite3`).
  - Nenhuma API key, secret ou chamada a endpoints privados de exchange.
  - Saldo fictício inicial configurável (10000.00 USDT) persistido em tabela única.
  - Modelo operacional Spot LONG exclusivo, limitado a uma única posição aberta por vez.
  - Notional fixo preliminar de 100.00 USDT por operação (a ser aprimorado pelo Risk Engine na FASE 6).
  - Execução one-shot com filtragem estrita de candles ainda em formação e deduplicação pelo timestamp do último candle fechado.
  - Transações atômicas com rollback em caso de falha, garantindo consistência entre carteira, posição e histórico.
- **Motivo**: Atendimento pleno à arquitetura local-first sem dependências externas adicionais (zero novas bibliotecas), confiabilidade transacional garantida pelo SQLite e isolamento completo contra riscos operacionais no mercado real.

---

### D012 — Risk Engine Determinístico e Local
- **Status**: Aceito
- **Data**: FASE 6
- **Contexto**: Necessidade de estabelecer uma camada intermediária explícita e mandatória de gestão e controle de risco entre a geração de sinais da estratégia e a execução de ordens simuladas no Paper Broker.
- **Decisão**: Implementar o motor de risco determinístico exclusivamente na Standard Library do Python (`src/finbot/risk.py`), com as seguintes diretrizes:
  - **Autoridade e Desacoplamento**: A estratégia não define tamanho de posição e o broker não decide se a ordem é permitida. Todo sinal deve receber autorização (`ALLOW`) ou bloqueio (`BLOCK`) com código padronizado (`RiskDecisionCode`).
  - **Isolamento de Rede**: O Risk Engine não importa CCXT nem realiza conexões de rede ou chamadas de IO, operando estritamente sobre estruturas em memória e dados validados.
  - **Precedência Conceitual Estrita**:
    1. *Proteção de Risco / Stop Loss Defensivo*: Se a posição aberta sofrer desvalorização >= 2.0% (`risk_stop_loss_pct`), a saída é disparada imediatamente com motivo `STOP_LOSS`, prevalecendo sobre qualquer sinal da estratégia.
    2. *Sinal SELL da Estratégia*: Se houver posição aberta, o encerramento é autorizado (`STRATEGY_SIGNAL`).
    3. *Sinal HOLD*: Nenhuma alteração patrimonial.
    4. *Sinal BUY da Estratégia*: Submetido à esteira de gates de risco (Posição Aberta / Max Position Notional, Kill Switch, Perda Diária Realizada, Cooldown por candles fechados e Saldo Disponível).
    5. *Sinal SELL sem Posição*: Ignorado sem erro.
  - **Inviolabilidade de Saídas**: Proteções de risco (Kill Switch, Cooldown e Limite de Perda Diária) jamais bloqueiam operações de venda destinadas a reduzir ou encerrar exposição.
  - **Cooldown Baseado em Candles**: O intervalo defensivo pós-encerramento (1 candle fechado) baseia-se em timestamps de candles fechados, sem temporizadores contínuos ou threads em background.
  - **Persistência e Migração Idempotente**: Registro de Kill Switch, último bloqueio de risco e motivo de saída (`exit_reason`) armazenados no SQLite existente via migração incremental que preserva bases anteriores sem destruição de dados.
- **Motivo**: Garantia matemática de contenção de prejuízos, observância de boas práticas quantitativas sem dependências de terceiros, preservação do princípio local-first e preparação estruturada da camada de risco para os futuros modos de operação.

---

### D013 — Adoção de Streamlit para Dashboard Local e Read-Only
- **Status**: Aceito
- **Data**: FASE 7
- **Contexto**: Necessidade de fornecer uma interface visual de fácil entendimento em tempo real para acompanhamento de patrimônio, posições, métricas de risco, sinais da estratégia e histórico de trades, preservando simplicidade local e segurança patrimonial.
- **Decisão**: Adotar a biblioteca `streamlit==1.64.0` para o dashboard visual local (`src/finbot/dashboard.py` e `src/finbot/metrics.py`):
  - **Modo Estritamente Read-Only**: O dashboard atua unicamente como camada de apresentação e leitura do SQLite local (`data/finbot_paper.sqlite3`). Não possui botões, endpoints ou capacidade técnica de emitir ordens de compra/venda, alterar saldos ou contornar o Risk Engine.
  - **Restrição de Rede Local (localhost)**: Vinculado estritamente à interface local `127.0.0.1` (`--server.address=127.0.0.1`), sem exposição para `0.0.0.0`, sem túneis remotos e sem autenticação externa nesta etapa.
  - **Desacoplamento de Métricas**: Módulo puro `metrics.py` para cálculo de win rate, fees, P/L não realizado e evolução patrimonial cumulativa, viabilizando testes unitários automatizados determinísticos sem necessidade de renderização visual.
  - **Responsividade e Prontidão Mobile**: Interface projetada com containers flexíveis e métricas responsivas do Streamlit, permitindo boa ergonomia tanto em monitores desktop quanto em telas menores de smartphones.
  - **Isolamento de Acesso Remoto**: O acesso remoto não foi implementado nesta fase; futuras fases avaliarão opções de distribuição segura (ex: PWA, gateway reverso seguro ou app dedicado).
- **Motivo**: Desenvolvimento rápido em Python, excelente integração nativa com DataFrames/pandas e SQLite, visual moderno e limpo sem necessidade de frameworks web pesados ou acoplamento de servidores adicionais.

---

### D014 — Automação de Ciclos Paper Trading via Windows Task Scheduler
- **Status**: Aceito
- **Data**: FASE 7.5
- **Contexto**: Necessidade de executar o Paper Trading de forma contínua e autônoma ao longo do tempo (intervalo de 1 minuto), preservando a filosofia local-first e sem transformar a aplicação em um serviço de background ou daemon complexo.
- **Decisão**: Adotar a automação externa via Windows Task Scheduler orquestrando scripts PowerShell (`scripts/run_paper.ps1` e `scripts/install_paper_task.ps1`):
  - **Preservação do Modelo One-Shot**: O FinBot não implementa loops infinitos (`while True`), threads permanentes ou bibliotecas externas de agendamento (zero frameworks como APScheduler, Celery ou Redis). O comando `python -m finbot.paper` permanece estritamente one-shot.
  - **Prevenção de Sobreposição Concorrente**: Tarefa configurada com política `MultipleInstances: IgnoreNew`, garantindo que um novo ciclo jamais seja iniciado se uma execução anterior ainda estiver em processamento.
  - **Deduplicação de Candles**: O timestamp do último candle fechado gravado no SQLite continua sendo a salvaguarda primária contra reprocessamento no mesmo minuto.
  - **Observabilidade Persistente**: Gravação do timestamp do último ciclo, último ciclo bem-sucedido, resultado e mensagem de execução em `paper_state`, viabilizando o monitoramento de frescor operacional (`RECENT` vs `STALE`) no dashboard e CLI.
  - **Recuperação Natural**: O agendador nativo do sistema operacional lida com reinicializações e falhas do processo sem risco de estados corrompidos ou threads zumbis.
- **Motivo**: Máxima simplicidade arquitetural, confiabilidade operacional nativa do Windows, separação clara entre motor de cálculo financeiro e agendamento temporal, e conformidade com o princípio de adicionar apenas o estritamente necessário.

---

### D015 — Telemetria Enxuta para Paper Soak Test e Rotação de Logs
- **Status**: Aceito
- **Data**: FASE 7.6
- **Contexto**: Preparação para um período de teste de estresse e estabilidade operacional contínua (*Paper Soak Test*) de 72 horas sem supervisão direta no Windows, exigindo observabilidade de falhas, métricas de execução e controle de espaço em disco.
- **Decisão**:
  - **Telemetria Enxuta em `paper_state`**: Utilizar a tabela existente de chave-valor do SQLite para rastrear contadores atômicos de ciclos (`total_cycles`, `successful_cycles`, `failed_cycles`, `deduplicated_cycles`), além de `soak_start_timestamp`, `last_error` e `last_error_timestamp`. Nenhuma tabela nova ou framework pesado de métricas foi adicionado.
  - **Isolamento de Falhas Transitórias**: Falhas de rede, timeouts ou indisponibilidade temporária de exchange incrementam o contador de falhas e registram o erro, mas jamais alteram ou corrompem o saldo fictício, a posição aberta, os trades executados ou o último candle processado. O próximo ciclo agendado recupera a saúde operacional sem intervenção manual.
  - **Rotação de Arquivos de Log**: Adoção de `RotatingFileHandler` da Standard Library com limite de 5 MB por arquivo e retenção de até 3 backups (`logs/finbot.log`), prevenindo saturação descontrolada de disco ao longo de execuções ininterruptas minuto a minuto.
- **Motivo**: Observabilidade diagnóstica completa, segurança patrimonial inegociável, isolamento contra falhas de infraestrutura e conformidade estrita com o princípio da menor intervenção necessária.

---

### D016 — Adoção de Repositório GitHub Privado para Sincronização e Backup sem CI/CD
- **Status**: Aceito
- **Data**: FASE 7.6 / Transição
- **Contexto**: Necessidade de manter backup privado do código, rastreamento de versões e fluxo de sincronização entre ambientes físicos distintos: Notebook (focado em desenvolvimento e commits) e PC Forte (focado em testes locais completos, Paper Runner, Dashboard e runtime 24/7).
- **Decisão**: Configurar repositório remoto privado no GitHub (`https://github.com/ricobeliko/FinBot.git`) exclusivamente como camada de versionamento e backup do código-fonte:
  - **Papel do Notebook**: Ambiente de desenvolvimento, escrita de código, execução de commits e envio (`git push origin main`).
  - **Papel do PC Forte**: Ambiente de execução local contínua, sincronização (`git pull origin main`), execução de testes automatizados locais (`python -m unittest discover tests`), Paper Runner periódico e visualização de Dashboard.
  - **Ausência Estrita de CI/CD**: Nenhum workflow do GitHub Actions (`.github/workflows/`), pipeline de nuvem, runner remoto ou deploy automático. O repositório é estritamente de armazenamento e transporte de código.
  - **Testes Unitários Versionados (`tests/`)**: A suíte de testes permanece integralmente versionada no Git para ser executada de forma autônoma e offline em cada máquina local.
  - **Isolamento de Estado Operacional (`data/finbot_paper.sqlite3`)**: O banco de dados SQLite local, dados de saldo paper, ordens simuladas, logs e variáveis de ambiente (`.env`) permanecem ignorados no `.gitignore` e restritos à máquina local em que operam.
- **Motivo**: Segurança do patrimônio de código sem dependência de plataformas de automação em nuvem, garantia de execução e testes 100% locais e preservação da integridade da máquina de execução contínua.

---

### D017 — Arquitetura Isolada do FinBot Lab para Backtesting Paralelo e Mitigação de Overfitting
- **Status**: Aceito
- **Data**: FASE 7.7
- **Contexto**: Necessidade de um laboratório quantitativo para testar combinações de parâmetros (grid sweep), utilizar múltiplos núcleos de CPU via paralelismo de processos e avaliar sistematicamente o risco de overfitting com divisão cronológica de dados (Train / Validation / Test).
- **Decisão**: Criar o pacote isolado `src/finbot/lab/` e dashboard dedicado `src/finbot/lab_dashboard.py` (porta 8502):
  - **Isolamento Total do Bot Operacional**: O Lab opera unicamente sobre dados históricos locais, sem jamais acessar, alterar ou criar `data/finbot_paper.sqlite3`, `paper_account`, `paper_position`, `paper_trades` ou o Task Scheduler. O Lab não possui autoridade para promover estratégias automaticamente para o bot operacional.
  - **Divisão Cronológica Estrita**: Particionamento temporal (60% Train, 20% Validation, 20% Test) sem embaralhamento (no-shuffle), evitando qualquer look-ahead bias ou contaminação entre partições.
  - **Reutilização da Lógica Financeira Oficial**: Sem duplicação de cálculo; as simulações reutilizam diretamente `run_backtest` de `finbot.backtest`.
  - **Paralelismo Seguro via Standard Library**: Adoção de `concurrent.futures.ProcessPoolExecutor` com suporte a `--workers auto` (`max(1, cpu_count - 1)`), garantindo determinismo idêntico entre execuções sequenciais e paralelas.
  - **Salvaguarda do Preset FULL**: Presets configuráveis (`smoke`, `standard`, `full`), onde `full` requer confirmação explícita (`--confirm-full`) para prevenir sobrecarga de computação no notebook.
  - **Validade do Dataset Conhecida**: Resultados do snapshot de 500 candles são explicitamente rotulados como `EXPLORATORY / ENGINEERING VALIDATION` e não constituem evidência estatística suficiente de robustez final.
- **Motivo**: Prover infraestrutura quantitativa profissional, reprodutível e determinística mantendo o bot operacional estritamente congelado e protegido.

---

### D018 — Auditoria Metodológica e Ingestão de Dataset Histórico Ampliado (10.000 candles)
- **Status**: Aceito
- **Data**: FASE 7.8
- **Contexto**: Necessidade de auditar rigorosamente o comportamento metodológico do FinBot Lab (isolamento de capital, ausência de transbordo de posições, blindagem do ranking pelo Treino, comportamento de warm-up da SMA) e disponibilizar um dataset histórico substancialmente maior (10.000 candles de 5m da Binance Spot, ~34,7 dias) para viabilizar pesquisas quantitativas robustas sem depender de conexão de rede durante as simulações.
- **Decisão**:
  - **Metodologia de Partições Independentes**: Cada fatia cronológica (Train 60%, Validation 20%, Test 20%) é avaliada de forma estritamente autônoma, iniciando com capital novo (`10000.0 USDT`) e posição zerada. Os primeiros `long_window` candles de cada fatia atuam como aquecimento interno (emitindo `HOLD`), prevenindo que métricas de Buy & Hold ou retornos da partição anterior contaminem a partição subsequente.
  - **Blindagem do Ranqueamento**: O ranking de candidatos é determinado exclusivamente pelo desempenho da partição de Treino (`train.return_pct`, etc.). As métricas de Validação e Teste são puramente diagnósticas (out-of-sample) e não possuem autoridade de seleção.
  - **Dataset Ampliado e Congelado**: Download reproduzível e paginado via script dedicado (`scripts/download_dataset.py`) de 10.000 candles fechados de 5m (`data/backtest/binance_BTCUSDT_5m_10000.json`, 1.7 MB), preservando o snapshot original de 500 candles (`binance_BTCUSDT_5m.json`). Integridade temporal (5m contínuos, ausência de duplicatas e OHLC válido) auditada e aprovada.
  - **Bateria Metodológica Automatizada**: Adição de 10 testes determinísticos em `test_lab_methodology.py` (totalizando 100 testes no projeto).
- **Motivo**: Consolidação de integridade científica e quantitativa prévia a qualquer esforço de força bruta em larga escala, mantendo o bot operacional no PC Forte congelado e protegido.

---

### D019 — Benchmark Técnico Externo do FinBot Lab (VectorBT, Jesse, Freqtrade e Backtesting.py)
- **Status**: Aceito
- **Data**: FASE 7.9A
- **Contexto**: Investigação comparativa de frameworks maduros (VectorBT Community 1.1.1, Jesse, Freqtrade Hyperopt e Backtesting.py 0.6.6) para determinar se o FinBot Lab deve ser mantido, complementado ou substituído, avaliando semântica de execução, paralelismo, métricas, licenças e complexidade operacional no dataset de 10.000 candles de 5m.
- **Decisão**:
  - **Manter FinBot Lab e Backtesting.py como Motor Principal**: O FinBot Lab preserva o isolamento metodológico temporal (Train 60% / Val 20% / Test 20%), blindagem contra vazamento de dados e compatibilidade 100% direta com a estratégia do bot.
  - **Otimização de Fatiamento (Slice Optimization) no Backtest**: A passagem de apenas a janela necessária (`data[-req:]`) elimina a complexidade quadrática de recálculo sobre séries longas, acelerando a execução em até 10x mantendo 100% de equivalência.
  - **Candidatura de VectorBT como Motor de Pré-Triagem (Screening)**: VectorBT demonstrou concordância exata na contagem de trades (576 trades no benchmark SMA 5/10), drawdown e retorno (divergência residual de apenas ~0,03% por arredondamento de taxas) quando configurado com sinais deslocados (`shift(1)`) e preço de execução em `Open`. Avaliar no futuro como acelerador para varreduras preliminares de 10.000+ combinações.
  - **Rejeição de Jesse para a Pilha Operacional**: Dependência estrita de PostgreSQL, Redis, Docker e compilação C de TA-Lib em ambiente Windows, violando a simplicidade local-first do projeto.
  - **Freqtrade como Referência Arquitetural**: Preservado apenas como inspiração técnica para testes de provocação de lookahead e funções de perda customizadas (Sharpe/Drawdown), sem adoção de dependências pesadas ou licença GPL-3.0.
- **Motivo**: Escolha baseada em evidência empírica, mantendo a simplicidade operacional, independência de infraestrutura e fidelidade às regras determinísticas do FinBot.

---

### D020 — Prova do Pipeline Híbrido VectorBT (Screening Train-Only) + FinBot Lab (OOS Evaluation)
- **Status**: Aceito
- **Data**: FASE 7.9B
- **Contexto**: Necessidade de acelerar o screening de milhares de combinações de parâmetros (1.000 a 10.000+) mantendo rigorosamente a semântica de execução do FinBot, separação temporal, ausência de lookahead e proteção contra data leakage no dataset de 10.000 candles de 5m.
- **Decisão**:
  - **Adoção do Pipeline Híbrido em Dois Estágios**:
    1. *Estágio 1 (Screening Bruto)*: VectorBT Community vetorizado via NumPy/Numba processa o grid em lotes (`batch_size = 1000`) estritamente sobre a partição de **TRAIN** (6.000 candles). Sinais observados no `Close[t]` são deslocados via `.shift(1)` e executados no preço `Open[t+1]`, com `fees=0.001` e `init_cash=10000.0`.
    2. *Estágio 2 (Diagnóstico Out-of-Sample)*: FinBot Lab (`finbot.lab.evaluator` / `Backtesting.py`) reavalia independentemente apenas os **Top N** candidatos (Top 20 / Top 50) selecionados no Estágio 1, gerando métricas completas para Train (60%), Validation (20%) e Test (20%).
  - **Alinhamento Semântico e Equivalência Verificada**: Teste com SMA 5/10 no Train comprovou paridade exata de contagem de trades (347 vs 347, 48 wins, 299 losses, 13.83% win rate) e ranking 100% idêntico no grid smoke de 9 combinações.
  - **Blindagem Formal Anti-Leakage**: Provado experimentalmente que mutações drásticas nas partições de Validation e Test produzem zero alteração no Top N gerado pelo screening de Train (100% idêntico).
  - **Isolamento de Dependência (Research-Only)**: O VectorBT permanece confinado exclusivamente ao ambiente de pesquisa (`.venv-research`) e não foi adicionado ao `pyproject.toml` ou `requirements.txt` da produção. O runtime operacional (Paper Runner, Risk Engine, Dashboard 8501) permanece 100% desacoplado e intocado.
- **Motivo**: Aceleração de ~100x na triagem exploratória (10.000 combinações avaliadas em ~91s), mantendo bounded memory (~2.19 GB RAM), determinismo estrito e integridade metodológica sem concessões.

---

### D021 — Adoção de Walk-Forward Analysis (WFA) Temporal com Screening Híbrido no FinBot Lab
- **Status**: Aceito
- **Data**: FASE 7.9C
- **Contexto**: Necessidade de validação quantitativa temporal dinâmica contra regimes de mercado mutáveis através de janelas deslizantes (*rolling windows*), assegurando que cada janela selecione parâmetros estritamente com base no passado disponível e seja avaliada de maneira puramente *out-of-sample* (OOS), sem *data leakage*.
- **Decisão**:
  - **Implementação do Módulo `finbot.lab.wfa`**:
    - Fatiamento determinístico de janelas deslizantes: Train (4.000 candles), Test (1.000 candles) e Step (1.000 candles), gerando 6 janelas temporais sequenciais cobrindo o dataset de 10.000 candles de 5m da Binance Spot (~34,7 dias).
    - Preservação de precedência temporal estrita: `train_end_time < test_start_time` auditado em cada janela.
    - Seleção Top N (20 candidatos) executada exclusivamente pelo screening VectorBT no Train de cada janela.
    - Reavaliação OOS independente de cada candidato no Test via FinBot Lab (`Backtesting.py`).
  - **Isolamento e Blindagem Anti-Leakage**: Provado por teste automatizado que mutações arbitrárias nos dados de teste não afetam os parâmetros selecionados pelo treino.
  - **Exportação Estruturada**: Persistência tabular em `data/lab/results/wfa/` (`wfa_windows.csv`, `wfa_summary.csv` e `wfa_results.json`) estruturada de forma padronizada para permitir futura ingestão em um *Experience Dataset*.
  - **Isolamento Operacional**: O WFA permanece uma ferramenta de laboratório/pesquisa offline. Nenhuma funcionalidade de Machine Learning, aprendizado online ou alteração do Paper Runner / Risk Engine foi introduzida.
- **Motivo**: Comprovação de consistência temporal, transparência na observação de degradação entre treino e teste em diferentes regimes de volatilidade, e consolidação metodológica sem violação do princípio *local-first*.

---

### D022 — Avaliação de Robustez e Stress Testing do WFA (Fase 7.9D)
- **Status**: Aceito
- **Data**: FASE 7.9D
- **Contexto**: Necessidade de descobrir experimentalmente quão sensíveis são os resultados observados no Walk-Forward Analysis (WFA) a pequenas perturbações controladas de custos (taxas), vizinhança de parâmetros, profundidade de seleção (Top N) e variações temporais de corte de janelas.
- **Decisão**:
  - **Implementação do Módulo `finbot.lab.robustness`**:
    - *Sensibilidade a Custos*: Avaliação sistemática de 4 níveis de comissão (`0.00075`, `0.00100`, `0.00125`, `0.00150`), revelando degradação linear de retorno sem alteração abrupta no volume de trades.
    - *Perturbação de Parâmetros (Vizinhança 3x3)*: Avaliação de vizinhos contíguos (`short ±1`, `long ±2`) para os parâmetros selecionados em cada janela. 100% das janelas exibiram comportamento de **PLATÔ** estável (desvio padrão interno ínfimo entre 0,03% e 1,00%), descartando hipóteses de "falésia" ou anomalias isoladas de sobreajuste.
    - *Sensibilidade ao Top N*: Preservação de grupos de 5, 10 e 20 candidatos exibiu taxa de retorno e positividade OOS rigorosamente invariantes (~17% de candidatos positivos, retorno médio de -0,96% a -0,99%).
    - *Sensibilidade Temporal*: Testes com janelas de Train de 3.000, 4.000 e 5.000 candles e Test de 500 candles confirmaram que a assimetria negativa e concentração de ganho em uma única janela (W3) é uma característica estrutural da estratégia de médias no período histórico, e não um artefato do tamanho da janela.
  - **Exportação Estruturada**: Persistência tabular em `data/lab/results/robustness/` (`robustness_summary.csv`, `robustness_windows.csv` e `robustness_results.json`).
  - **Isolamento e Segurança**: Metodologia 100% diagnóstica e descritiva. Nenhuma decisão automática, pontuação mágica ou alteração no bot operacional foi permitida.
- **Motivo**: Obtenção de evidências quantitativas fidedignas sobre a estabilidade local e fragilidades estruturais da estratégia antes de qualquer avanço para modelagem de aprendizado.

---

### D023 — Fundação do Experience Dataset e Blindagem Anti-Leakage (Fase 7.9E)
- **Status**: Aceito
- **Data**: FASE 7.9E
- **Contexto**: Necessidade de estruturar uma memória persistente de experiências no FinBot ("o que o bot sabia no momento da decisão, o que decidiu/executou e o que aconteceu posteriormente") como base preparatória para futura aprendizagem adaptativa, assegurando separação metodológica estrita entre Decision Time e Outcome Time para impedir qualquer contaminação ou vazamento de dados futuros (*data leakage*).
- **Decisão**:
  - **Separação Formal entre Decision Time e Outcome Time**:
    - *DecisionContext (FEATURE-SAFE)*: Registra exclusivamente variáveis disponíveis no instante `decision_at` (`candle_timestamp`, `symbol`, `timeframe`, `price`, OHLCV do candle fechado, `strategy_name`, `strategy_version`, `strategy_parameters`, `signal`, `signal_reason`, `position_before`, `risk_decision`, `risk_reason`, `risk_allowed`, dados de execução se aplicável). `to_feature_dict()` extrai exclusivamente estes campos.
    - *OutcomeContext (OUTCOME-ONLY)*: Registra exclusivamente informações conhecidas após `decision_at` (`outcome_at`, `exit_price`, `realized_pnl`, `realized_return`, `fees`, `mfe`, `mae`, `trade_duration`, horizontes de retorno futuro `future_return_5/20/50/100`, `outcome`). Inicia nulo/vazio para decisões em andamento.
  - **Contrato Anti-Leakage e Validação Temporal**:
    - Validação matemática estrita: `outcome_at >= decision_at` quando ambos existem, disparando exceção imediata caso ocorra violação de precedência temporal.
    - Campos desconhecidos permanecem estritamente `NULL` / `None`, sendo proibido o preenchimento artificial ou aproximações com `0`.
  - **Experiência Além de Trade**: A arquitetura suporta tanto *Decision Experiences* (sinais `HOLD` ou decisões bloqueadas pelo Risk Engine, sem execução financeira) quanto *Trade Experiences* (operações executadas com desfecho posterior).
  - **Persistência SQLite e Deduplicação**:
    - Criação idempotente da tabela `experiences` e índices associados no SQLite local (`data/finbot_paper.sqlite3`), compatível com o banco operacional existente sem necessidade de reset ou destruição de dados.
    - Chave única de integridade e deduplicação baseada em `UNIQUE(source, source_id)`, evitando registros duplicados.
  - **Exportação Determinística**:
    - Métodos `export_to_csv` e `export_to_json` determinísticos, ordenados cronologicamente e protegidos no `.gitignore` sob `data/lab/results/experience/`.
  - **Isolamento**: Nenhuma dependência pesada de ML, nenhum ajuste automático de risco ou estratégia, e preservação integral do ambiente operacional e do Paper Soak Test de 72h no PC Forte.
- **Motivo**: Criação de uma fundação sólida, determinística e auditável para o dataset de experiências, viabilizando as futuras Fases 7.9F (Features + Labels) e 7.9G (Adaptive Learning) com garantia matemática contra vazamento temporal.

---

### D024 — Especificação Matemática de Features e Labels sem Leakage (Fase 7.9F)
- **Status**: Aceito
- **Data**: FASE 7.9F
- **Contexto**: Necessidade de transformar as experiências armazenadas no Experience Dataset em conjuntos concretos e determinísticos de Features (para entrada de modelos) e Labels (variáveis alvo de retornos futuros), assegurando conformidade matemática irrestrita com a semântica operacional do FinBot e eliminação total de *look-ahead bias* ou *data leakage*.
- **Decisão**:
  - **Preservação da Semântica Temporal Oficial**:
    - `Candle[t]`: candle fechado que gera a decisão no instante `Close[t]`.
    - `Candle[t+1]`: candle onde ocorre a execução no preço de abertura `Open[t+1]` (ou `execution_price`).
    - `Candle[t+N]`: candle de encerramento do horizonte futuro no preço de fechamento `Close[t+N]`.
  - **Conjunto de Features Decision-Safe (`FeatureSet`)**:
    - *Mercado*: `price`, `open`, `high`, `low`, `close`, `volume` no instante da decisão.
    - *Estratégia e Indicadores*: `short_window`, `long_window`, `sma_short`, `sma_long`, `sma_distance` (`sma_short - sma_long`), `sma_ratio` (`sma_short / sma_long`).
    - *Estado*: `signal`, `signal_reason`, `position_before`, `risk_decision`, `risk_reason`, `risk_allowed`.
    - *Contexto Temporal UTC*: `hour` (0..23) e `day_of_week` (0..6), derivados unicamente de `decision_at`.
    - *Blindagem*: Nenhuma informação posterior a `Close[t]` é permitida no `FeatureSet`.
  - **Definição Matemática dos Labels Futuros (`LabelSet`)**:
    - Preço de Referência: $P_{ref} = Open[t+1]$ (ou `execution_price`).
    - Retorno Futuro para Horizonte $N \in \{5, 20, 50, 100\}$:
      $$\text{future\_return\_N} = \frac{Close[t+N] - P_{ref}}{P_{ref}}$$
    - *Tratamento Estrito de Insuficiência*: Se $t+N \ge \text{len(candles)}$, o valor permanece obrigatoriamente `None` (`NULL`). É expressamente proibido preencher com 0 ou aproximar valores ausentes.
    - *Postponement de Labels Categóricos/Direcionais e MFE/MAE*: Adoção de thresholds arbitrários para categorização de mercado (`UP/DOWN/FLAT`) e MFE/MAE foi postergada para a Fase 7.9G para evitar heurísticas não fundamentadas.
  - **Módulo e Exportação**:
    - Implementação de `src/finbot/features.py` exclusivamente na Standard Library do Python (zero novas dependências).
    - Funções de exportação `export_features_labels_csv` e `export_features_labels_json` em `data/lab/results/features_labels/` (ignorado no Git).
  - **Isolamento**: Zero frameworks de ML instalados, nenhum modelo treinado, nenhum ajuste dinâmico de risco e runtime operacional mantido intacto.
- **Motivo**: Estabelecer um contrato matemático irrevogável, auditado e reproduzível entre o que o FinBot sabia no momento da decisão e o que o mercado fez posteriormente.

---

### D025 — Adaptive Learning Foundation (Fase 7.9G)
- **Status**: Aceito
- **Data**: FASE 7.9G
- **Contexto**: Estabelecer e validar o primeiro pipeline determinístico de aprendizado adaptativo do FinBot (`Experience Dataset -> Features + Labels -> Temporal Dataset -> Baseline -> Modelo Simples -> Validation -> Final Test -> Relatório de Aprendizado`), sem introduzir Machine Learning no runtime de produção e sem alterar a tomada de decisão da Strategy Engine ou do Risk Engine.
- **Decisão**:
  - **Objetivo Científico e Metodológico**: Avaliar de forma estritamente offline e auditada se as experiências passadas do FinBot contêm sinal preditivo sobre o comportamento futuro do mercado, medindo se um modelo linear regularizado acrescenta informação em relação a um baseline estatístico.
  - **Fonte Canônica e Auditoria de Dataset**:
    - O banco de paper trading (`data/finbot_paper.sqlite3`) possui apenas 3 trades no momento, disparando corretamente o status de salvaguarda `INSUFFICIENT_SAMPLE`.
    - Como fonte canônica com significância estatística real e sem dados fabricados, utilizou-se o dataset histórico oficial de 10.000 candles (`data/backtest/binance_BTCUSDT_5m_10000.json`) gerando 575 experiências canônicas completas a partir da execução da estratégia SMA 5/10.
  - **Target Escolhido**:
    - `future_return_20`: Retorno contínuo a 20 candles futuros, calculado estritamente como $(Close[t+20] - Open[t+1]) / Open[t+1]$ conforme o contrato da Fase 7.9F.
  - **Features Decision-Safe (14 variáveis)**:
    - Exclusivamente variáveis conhecidas no instante de fechamento do candle de decisão $Close[t]$: `price`, `open`, `high`, `low`, `close`, `volume`, `short_window`, `long_window`, `sma_short`, `sma_long`, `sma_distance`, `sma_ratio`, `hour`, `day_of_week`.
    - Proibição estrita de qualquer campo de outcome (`future_return_*`, `realized_pnl`, `exit_price`, etc.) no vetor de entrada.
  - **Split Temporal Estrito (NO SHUFFLE)**:
    - Divisão cronológica 60% Train (345 amostras) / 20% Validation (115 amostras) / 20% Test (115 amostras).
    - Garantia matemática de precedência temporal: $\max(Train) < \min(Val) < \min(Test)$. Rejeição automática com erro se houver embaralhamento ou desordem.
  - **Pré-processamento sem Leakage**:
    - `StandardScaler` (com fallback puro em NumPy para compatibilidade total entre `.venv` e `.venv-research`) ajustado (*fit*) exclusivamente sobre os dados de Treino, sendo apenas aplicado (*transform*) sobre Validação e Teste.
  - **Baseline Estatístico**:
    - Estimador constante baseado na média do Treino (`DummyRegressor(strategy="mean")` / média escalar de Treino), sem acesso a Validação ou Teste.
  - **Primeiro Modelo Regularizado**:
    - Regressão Ridge ($\alpha=1.0$), selecionada por sua simplicidade, estabilidade analítica, interpretabilidade e baixo risco de overfitting em amostras pequenas.
  - **Métricas Multidimensionais**:
    - Erro e correlação: MAE, RMSE, $R^2$, Acurácia Direcional (concordância de sinal predito vs real), correlação de Pearson.
    - Diagnóstico econômico não-operacional: retorno real médio condicionado ao sinal da predição ($\hat{y} > 0$ vs $\hat{y} \le 0$).
  - **Resultado do Experimento Real (10k Candles)**:
    - *Train*: Baseline MAE = 0.003048 vs Ridge MAE = 0.002975 ($R^2 = 0.1052$, Acurácia Direcional = 53.91%).
    - *Validation*: Baseline MAE = 0.003387 vs Ridge MAE = 0.003605 ($R^2 = -0.0380$, Acurácia Direcional = 51.30%).
    - *Test*: Baseline MAE = 0.003608 vs Ridge MAE = 0.004995 ($R^2 = -0.4386$, Acurácia Direcional = 48.70%).
    - *Conclusão Registrada Honestamente*: `MODEL_DOES_NOT_BEAT_BASELINE`. O modelo linear regularizado não superou o baseline estático nas partições out-of-sample, confirmando a hipótese de ruído em horizontes curtos de 5m e validando a solidez da metodologia de rejeição.
  - **Por que isso NÃO é Adaptive Trading**:
    - O modelo é 100% offline e pesquisa-first.
    - Zero integração com o Paper Runner, Risk Engine ou Strategy Engine.
    - Nenhuma ordem enviada, nenhum parâmetro operacional alterado dinamicamente.
    - Validação de modelos e governança pertencem à Fase 7.9H; paper trading adaptativo pertence à Fase 7.9I.
- **Motivo**: Validar a infraestrutura e integridade científica do aprendizado de máquina no FinBot, garantindo transparência, ausência de leakage e rigor estatístico antes de qualquer transição para validação de modelos.

---

### D026 — Model Validation and Registry (Fase 7.9H)
- **Status**: Aceito
- **Data**: FASE 7.9H
- **Contexto**: Estabelecer um sistema local, determinístico, auditável e imutável para validação formal, registro, controle de versão e governança de modelos de pesquisa de aprendizado adaptativo gerados no FinBot Lab (`src/finbot/lab/model_registry.py`), impedindo que modelos não validados ou sem generalização sejam considerados para fases posteriores.
- **Decisão**:
  - **Objetivo**: Criar uma camada formal de auditoria e governança científica entre o treinamento (`Adaptive Learning`) e eventuais estudos em papel (`Adaptive Paper`), garantindo que apenas modelos com integridade de dados comprovada, ausência de leakage e superioridade out-of-sample (OOS) sobre o baseline possam atingir o status `VALIDATED`.
  - **Estados Formais do Registry**:
    - `CANDIDATE`: Modelo recém-treinado e registrado, aguardando submissão formal ao Validation Gate.
    - `VALIDATED`: Modelo que foi submetido ao Validation Gate e aprovado em 100% dos testes de integridade metodológica e demonstrou superioridade de generalização out-of-sample em relação ao baseline estático.
    - `REJECTED`: Modelo que falhou em qualquer teste de integridade ou que não superou o baseline nas partições out-of-sample (Validação e Teste).
    - `REVOKED`: Modelo anteriormente `VALIDATED` que foi posteriormente invalidado devido a nova evidência empírica, revisão de dataset ou detecção de anomalia posterior. O registro original e o motivo da revogação são preservados integralmente.
  - **Identificador de Modelo Determinístico (`model_id`)**:
    - Construído exclusivamente via hash criptográfico SHA-256 do payload canônico de identidade científica (dataset fingerprint, source, symbol, timeframe, target, target fingerprint, feature fingerprint, model type, hiperparâmetros, flags de pré-processamento/shuffle e ranges temporais dos splits).
    - Formato: `model_<sha256[:16]>`. Execuções repetidas da mesma especificação produzem rigorosamente o mesmo ID.
  - **Fingerprints de Integridade**:
    - *Dataset Fingerprint*: SHA-256 de timestamps, fechamentos, volumes e contagem de candles, detectando qualquer alteração histórica.
    - *Feature Fingerprint*: SHA-256 da lista e ordem exata das features e versão do conjunto, detectando alterações estruturais de entrada.
    - *Target Fingerprint*: SHA-256 do nome do alvo, definição semântica, horizonte e preço de referência.
  - **Validation Gate Determinístico**:
    - Executa auditoria automatizada em 7 verificações: integridade do dataset, integridade e ausência de campos proibidos nas features, integridade do target, ordenação temporal estrita ($\max(Train) < \min(Val) < \min(Test)$), ausência de shuffle e vazamento de pré-processamento, consistência do `model_id` e superioridade out-of-sample vs baseline.
    - *Regra de Generalização*: A decisão de validação é estritamente baseada nas partições OOS (Validação e Teste), sendo proibido usar métricas de Treino para mascarar deficiências de generalização.
  - **Registro do Modelo Real da F7.9G**:
    - O modelo Ridge Regression ($\alpha=1.0$) treinado na Fase 7.9G sobre o dataset canônico de 10.000 candles de 5m foi registrado e submetido ao Validation Gate, sendo classificado com status `REJECTED` pelo motivo `MODEL_DOES_NOT_BEAT_BASELINE` (MAE Val: 0.003605 vs Base: 0.003387; MAE Test: 0.004995 vs Base: 0.003608). O resultado foi aceito de forma honesta e transparente.
  - **Persistência Append-Only e Imutabilidade**:
    - Implementação de tabela `model_registry` e tabela de histórico `model_audit_log` em SQLite local (`data/lab/results/model_registry/model_registry.sqlite3`).
    - Nenhuma linha de histórico é sobrescrita silenciosamente; conflitos de mesmo ID com dados científicos divergentes disparam erro de integridade; registros repetidos idênticos são idempotentes.
    - Relatórios e manifests exportados em CSV e JSON em `data/lab/results/model_registry/` (ignorado no Git).
  - **Segurança Arquitetural e Ausência de Integração Operacional**:
    - O Model Registry é 100% restrito a `src/finbot/lab/` (pesquisa local).
    - Prova automatizada em suíte de testes garante que `finbot.paper`, `finbot.risk` e `finbot.strategy` não possuem nenhuma importação ou dependência do Registry.
    - Zero ordens reais, zero chamadas à Binance e runtime operacional mantido intacto.
- **Motivo**: Assegurar governança, rastreabilidade e rigor científico no ciclo de vida de modelos preditivos, impedindo que modelos deficientes ou contaminados por vazamento temporal avancem para etapas de execução financeira simulada ou real.

---

### D027 — Adaptive Paper Safety Architecture (Fase 7.9I)
- **Status**: Aceito
- **Data**: FASE 7.9I
- **Contexto**: Desenvolver a infraestrutura de execução experimental adaptativa em Paper Trading com Shadow Mode e Adaptive Mode sob governança rigorosa do Model Registry, assegurando que modelos de machine learning só possam ser avaliados ou influenciar decisões de forma controlada, com fallback seguro, fail-closed por padrão e soberania irrestrita do Risk Engine e da Strategy Engine.
- **Decisão**:
  - **Hierarquia Operacional e Preservação Arquitetural**:
    - A Strategy Engine existente (SMA Crossover) permanece como a autoridade primária e geradora do sinal base em todos os ciclos.
    - O Risk Engine existente mantém soberania absoluta e poder de veto sobre 100% das intenções operacionais geradas, sejam elas originadas pela estratégia convencional ou pela recomendação adaptativa do modelo.
    - O Paper Broker (`PaperStorage.execute_trade_transaction`) e os mecanismos de execução financeira fictícia permanecem 100% inalterados e protegidos contra alterações destrutivas.
  - **Modos Operacionais Suportados**:
    - `off` (**Default obrigatório**): A camada adaptativa permanece inativa. A execução segue estritamente a estratégia convencional e o Risk Engine sem qualquer sobrecarga ou alteração comportamental.
    - `shadow`: O modelo recebe os dados no momento da decisão, calcula a inferência e registra formalmente no SQLite a recomendação adaptativa e métricas de concordância/divergência (`MODEL_DISAGREEMENT`), mas `final_signal` permanece **estritamente idêntico** ao `existing_signal`. Nenhuma ordem é alterada pelo modelo.
    - `adaptive`: O modelo validado propõe recomendações (`LONG_BIAS` / `NO_LONG_BIAS`) que podem orientar a tomada de decisão para avaliação do Risk Engine. Caso o modelo seja recusado ou ocorra qualquer erro, o sistema ativa fallback imediato para a estratégia convencional.
  - **Requisito Obrigatório de Model Registry e Status VALIDATED**:
    - Apenas modelos formalmente cadastrados no `ModelRegistry` com status `VALIDATED` pelo Validation Gate podem ser carregados para execução.
    - Modelos com status `CANDIDATE`, `REJECTED` ou `REVOKED` são bloqueados categoricamente em tempo de carga (`load_validated_model`).
    - Modelos não encontrados no Registry (`MODEL_NOT_FOUND`) ou ausência de modelo configurado (`NO_MODEL_CONFIGURED`) são bloqueados.
    - O único modelo real registrado até o momento (`model_b3e792893e42fd40`, Ridge Regression) permaneceu com status `REJECTED`, sendo expressamente recusado em todos os testes reais.
  - **Verificação Criptográfica de Integridade e Fingerprints**:
    - Antes de qualquer inferência, o manifesto do modelo é reauditado contra seus hashes criptográficos: dataset fingerprint, feature fingerprint e target fingerprint.
    - Qualquer divergência ou adulteração resulta em bloqueio imediato com erro `MODEL_INTEGRITY_FAILURE` (fail-closed).
  - **Princípio Fail-Closed e Fallback Seguro**:
    - Qualquer anomalia na carga, ausência de parâmetros, erro de pré-processamento, exceção de cálculo ou valor numérico inválido (`NaN` ou `Inf`) na predição ativa imediatamente o fallback para a estratégia convencional, registrando o motivo de fallback e impedindo que exceções se propaguem ou interrompam o Paper Runner.
  - **Limitações Estritas do Modo Adaptativo**:
    - O FinBot permanece estritamente Long-Only Spot (sem vendas a descoberto / short).
    - O modelo adaptativo emite apenas recomendações direcionais simples (`LONG_BIAS` / `NO_LONG_BIAS`), sem forçar entradas em posições já existentes (`MAX_POSITION`) nem burlar regras de risco, cooldown ou kill switch.
  - **Dataset Separado de Predições Adaptativas (`adaptive_predictions`)**:
    - Armazenamento em tabela SQLite dedicada na base do Paper Trading, auditando `prediction_id`, `timestamp`, `model_id`, `model_status`, `prediction`, `existing_signal`, `adaptive_recommendation`, `final_signal`, `is_disagreement`, `risk_decision` e `fallback_reason`.
    - Separação estrita entre predições de decisão e o dataset de experiências/outcomes (`experiences`).
  - **Ausência Completa de Live Trading**:
    - Nenhuma credencial privada da Binance é utilizada; nenhuma ordem real é enviada; zero live trading. O ambiente operacional permanece local-first e o Paper Soak de 72h no PC Forte permaneceu ininterrupto e intocado.
- **Motivo**: Estabelecer um arcabouço de segurança definitivo para a introdução progressiva de inteligência adaptativa no FinBot, garantindo contenção de riscos, reprodutibilidade, observabilidade e proteção total contra regressões operacionais.

---

### D028 — Binance Private Integration Foundation and Read-Only Live Boundary (Fase 8.1)
- **Status**: Aceito
- **Data**: FASE 8.1
- **Contexto**: Estabelecer a fundação arquitetural para a integração privada com a Binance Spot via CCXT (`src/finbot/private_exchange.py`), garantindo autenticação segura, fronteira estrita entre Paper e Live, conformidade fail-closed, higienização rigorosa de credenciais e proibição absoluta de ordens reais nesta fase inicial de transição.
- **Decisão**:
  - **Módulo Isolado de Private Exchange (`src/finbot/private_exchange.py`)**:
    - Reutilização da biblioteca CCXT já adotada no projeto, com `enableRateLimit: True` e foco exclusivo em Spot.
    - Encapsulamento de chamadas autenticadas em métodos especializados com tipagem forte e precisão `Decimal` para saldos.
  - **Fronteira Estrita entre Paper e Live**:
    - Configuração explícita `trading_mode: str = "paper"` adicionada a `Config` e variáveis de ambiente (`TRADING_MODE`).
    - Modos permitidos: `"paper"`, `"live"`. Default obrigatório: `"paper"`. Qualquer valor inválido reverte automaticamente para `"paper"`.
    - O modo `paper` é impedido categoricamente de chamar endpoints privados ou instanciar o cliente privado (`InvalidConfigurationError`). O Paper Broker e o Paper Runner permanecem 100% isolados da API privada.
  - **Escopo Estritamente READ-ONLY (Fase 8.1)**:
    - Métodos implementados exclusivamente para inspeção da conta e saldos:
      - `get_account_status() -> AccountStatus` (permissões da conta, flags `canTrade`, `canWithdraw`, `canDeposit`, tipo de conta);
      - `get_balances(non_zero_only=True) -> dict[str, BalanceData]` (saldos com precisão Decimal);
      - `get_balance(asset) -> BalanceData` (consulta de saldo específico com fallback seguro para zeros);
      - `get_account_snapshot() -> AccountSnapshot` (snapshot estruturado e consolidado com timestamp UTC).
  - **Barreiras Arquiteturais contra Execução de Ordens**:
    - Zero endpoints de execução de ordens nesta fase.
    - Métodos de ordem declarados (`create_order`, `cancel_order`) levantam imediatamente `LiveTradingBlockedError`.
    - A flag `can_trade` do snapshot reflete estritamente a informação devolvida pela Binance e **não autoriza** nem desbloqueia execução de ordens na aplicação.
  - **Gestão Segura de Credenciais e Proteção de Segredos**:
    - Credenciais fornecidas exclusivamente via variáveis de ambiente (`BINANCE_API_KEY` e `BINANCE_API_SECRET`).
    - NUNCA hardcoded no código, nunca persistidas em SQLite, nunca gravadas em artefatos ou datasets.
    - `repr=False` aplicado aos campos de credenciais em `Config` e mascaramento customizado em `BinancePrivateExchange`, impedindo vazamento via `repr()`, `str()` ou `print()`.
    - Sanitização ativa em mensagens de erro e exceções (`sanitize_secret_text`), substituindo qualquer ocorrência de chaves por `[REDACTED]`.
  - **Princípio Fail-Closed**:
    - Credenciais ausentes ou vazias levantam `CredentialsMissingError`.
    - Falhas de autenticação levantam `AuthenticationError`.
    - Violações de rate limit levantam `RateLimitError`.
    - Erros de rede, DNS e timeouts levantam `NetworkError`.
    - Respostas malformadas levantam `PrivateExchangeError`.
    - Nenhum erro produz fallback silencioso para simulação ou operação real.
- **Motivo**: Construir a base de comunicação privada com a exchange sob padrões institucionais de segurança e contenção de risco, viabilizando reconciliação e auditoria de saldos antes de qualquer passo em direção ao envio de ordens.

---

### D029 — Windows Credential Manager for Binance Secrets
- **Status**: Aceito
- **Data**: FASE 8.2A
- **Contexto**: Eliminar qualquer armazenamento de credenciais reais da Binance em arquivos de texto plano (`.env`, `.json`, `.yaml`), variáveis de ambiente de processo ou bancos de dados locais. No ambiente operacional de produção (PC Forte), as credenciais devem ser gerenciadas por um cofre criptográfico nativo do sistema operacional com suporte a controle de acesso por usuário e criptografia de chave de máquina (DPAPI / LSASS).
- **Decisão**:
  - **Adoção do Windows Credential Manager**:
    - As credenciais de produção da Binance Spot (`api_key` e `api_secret`) passam a ser armazenadas exclusivamente no Windows Credential Manager sob o target canônico `FinBot/Binance/Production`.
    - Implementação nativa e enxuta via `ctypes` interagindo com `Advapi32.dll` (`CredReadW`, `CredWriteW`, `CredDeleteW`, `CredFree`), sem introduzir dependências externas pesadas ou serviços em nuvem.
  - **Abstração por Provedor (`CredentialProvider`)**:
    - Criação da interface abstrata `CredentialProvider` em `src/finbot/credentials.py`.
    - Implementação oficial para produção: `WindowsCredentialProvider`.
    - Implementação oficial para testes automatizados: `FakeCredentialProvider`, garantindo que os testes unitários sejam determinísticos e nunca acessem o cofre real do Windows nem dependam de conectividade externa.
  - **Isolamento de Ambientes**:
    - **PC Forte (Execução de Produção / Paper Soak 24/7)**: Único repositório autorizado para armazenamento da credencial real no Windows Credential Manager.
    - **Notebook de Desenvolvimento / Monitoramento**: Não possui as credenciais cadastradas e opera sob `PRIVATE_READ_TEST = NOT_RUN_NO_CREDENTIALS`, prevenindo contaminação acidental ou versionamento de chaves.
  - **Rejeição Estrita de Credenciais em Variáveis de Ambiente**:
    - `get_config()` em `src/finbot/config.py` não carrega chaves privadas de variáveis de ambiente.
    - Proibição absoluta de armazenamento de segredos em arquivos `.env`, `.json`, `.yaml`, `.sqlite3`, `.csv`, logs ou código-fonte.
  - **Proteção Ativa em Memória e Exceções**:
    - Dataclass `BinanceCredentials` implementa `repr=False` e representação customizada `BinanceCredentials(api_key=[PROTECTED], api_secret=[PROTECTED])`.
    - Higienização contínua de logs e mensagens de erro via `sanitize_secret_text`.
    - `BinancePrivateExchange` obtém credenciais em memória estritamente no momento da instanciação.
  - **Preservação Integral do Modo Paper**:
    - O modo `paper` (`TRADING_MODE=paper`, default obrigatório) não consulta o Windows Credential Manager nem exige chaves privadas para executar, mantendo os ciclos de Paper Trading completamente desacoplados.
  - **Princípio Fail-Closed**:
    - Se o target não for encontrado no Windows Credential Manager ou se as credenciais forem vazias, o FinBot levanta `CredentialsMissingError` imediatamente, impedindo chamadas de rede, criação de ordens ou fallbacks silenciosos.
  - **CLI Administrativa Segura**:
    - Comandos interativos auditáveis: `python -m finbot.credentials setup` (com entrada de segredo oculta via `getpass`), `status` (sem exibição de valores) e `remove` (com confirmação explícita obrigatória).
- **Motivo**: Atender aos mais rigorosos padrões institucionais de segurança para algoritmos de negociação, eliminando riscos de exfiltração acidental de chaves via Git, cópias de arquivos ou despejos de memória e logs.

---

### D030 — Secure Local Credential Enrollment GUI (Fase 8.2B)
- **Status**: Aceito
- **Data**: FASE 8.2B
- **Contexto**: No ambiente operacional do PC Forte, o cadastro via terminal com entrada oculta (`python -m finbot.credentials setup` com `getpass`) causou truncamento acidental na colagem do segredo HMAC (`KEY_LEN = 64`, `SECRET_LEN = 2`), resultando no erro Binance code -1022 ("Signature for this request is not valid."). Havia necessidade de fornecer uma interface gráfica local, simples e segura para permitir ao operador colar, visualizar (opcionalmente) e cadastrar a API Key e o API Secret com total confiabilidade, sem depender de entrada cega no terminal e sem introduzir novas dependências externas.
- **Decisão**:
  - **Interface Gráfica Local Simples (Tkinter)**:
    - Implementação de `src/finbot/credentials_gui.py` utilizando exclusivamente o pacote `tkinter` da Standard Library do Python (zero novas dependências).
    - A GUI existe **exclusivamente para o cadastro/enrollment local seguro de credenciais** e **NÃO** constitui painel de controle operacional ou de trading.
  - **Máscara Visual Estrita e Alternância Controlada**:
    - O campo de API Secret é renderizado mascarado por padrão com `show="*"`.
    - Checkbox "Mostrar API Secret" permite ao operador alternar a visibilidade sob demanda para conferência visual prévia à confirmação.
  - **Validação Preventiva sem Premissas Arbitrárias**:
    - Rejeição de campos vazios, espaços puros e quebras de linha (`\n`, `\r`).
    - Verificação de comprimento mínimo (`len < 16`), impedindo categoricamente a gravação de segredos truncados (como o caso real `SECRET_LEN=2`) sem codificar comprimentos rígidos arbitrários da Binance.
    - Aplicação de `strip()` estritamente nas extremidades.
  - **Armazenamento Exclusivo no Windows Credential Manager**:
    - Integração direta com o `WindowsCredentialProvider` já existente sob o target canônico `FinBot/Binance/Production`.
    - Proibição absoluta de persistência em arquivos (`.env`, `.json`, `.yaml`, SQLite, CSV) ou variáveis de ambiente.
  - **Proteção Total contra Vazamento em Logs e Diálogos**:
    - API Key e API Secret nunca são impressos, nunca são registrados em logs e nunca são exibidos em exceções ou caixas de mensagem (`messagebox`).
    - Mensagem de sucesso padronizada e descritiva: `"Credenciais Binance armazenadas com segurança."`.
  - **Limpeza Imediata em Memória**:
    - Após o salvamento bem-sucedido ou cancelamento, os campos de entrada e variáveis de controle da GUI são limpos imediatamente da memória.
  - **Desacoplamento Estrito de Rede e Ordens**:
    - O ato de salvar na GUI **NÃO realiza nenhuma chamada à Binance**. Cadastro e teste de conectividade permanecem operações estritamente separadas.
    - Ordens reais continuam categoricamente bloqueadas (`create_order` e `cancel_order` permanecem levantando `LiveTradingBlockedError`).
  - **Pontos de Entrada CLI**:
    - Invocação direta via `python -m finbot.credentials_gui`.
    - Suporte integrado à ação `gui` na CLI existente: `python -m finbot.credentials gui`.
    - Os comandos existentes `status`, `setup` e `remove` continuam funcionando sem qualquer alteração.
- **Motivo**: Eliminar falhas operacionais decorrentes de colagem cega no terminal e fornecer um mecanismo ergonômico, confiável e inviolável para o operador registrar suas credenciais no Windows Credential Manager antes da execução de testes read-only.

---

### D031 — Binance Private API Read-Only Operational Validation (Fase 8.2C)
- **Status**: Aceito
- **Data**: FASE 8.2C
- **Contexto**: Com a implementação do armazenamento seguro no Windows Credential Manager (Fase 8.2A) e da GUI local de cadastro (Fase 8.2B), fez-se necessária a homologação operacional real no ambiente oficial do PC Forte (`C:\Projetos\FinBot`), verificando se a autenticação HMAC e as consultas privadas de leitura funcionavam contra os servidores de produção da Binance Spot sem comprometer a política de bloqueio de ordens e sem registrar informações patrimoniais privadas.
- **Decisão**:
  - **Autenticação Real Homologada com Sucesso**:
    - Execução controlada dos métodos de leitura da exchange privada no PC Forte:
      - `BinancePrivateExchange.get_account_status()` -> `PASS` (resposta estruturada `AccountStatus` recebida com sucesso).
      - `BinancePrivateExchange.get_balances()` -> `PASS` (ativos recuperados com sucesso).
  - **Windows Credential Manager como Fonte Única da Verdade**:
    - A homologação confirmou que o Windows Credential Manager (target `FinBot/Binance/Production`) atende perfeitamente ao runtime 24/7 sem qualquer dependência de arquivos planos (`.env`, `.json`), logs ou variáveis de ambiente.
  - **GUI como Mecanismo Oficial de Enrollment**:
    - O incidente de erro Binance -1022 ("Signature for this request is not valid.") foi formalmente rastreado como truncamento da entrada oculta do terminal legado (`getpass` havia gravado apenas 2 caracteres do secret). A GUI Tkinter da Fase 8.2B corrigiu o cadastro em caráter definitivo, tornando-se o método oficial e preferencial para inclusão de credenciais.
  - **Separação Estrita entre Private Read Access e Live Order Execution**:
    - A capacidade técnica de ler dados autenticados (status da conta e saldos) permanece estritamente dissociada de qualquer envio de ordens.
    - Os métodos `create_order` e `cancel_order` permanecem bloqueados de forma fail-closed (`LiveTradingBlockedError`). Nenhuma ordem real foi criada, alterada ou cancelada na homologação.
  - **Configuração de Perímetro Seguro da API Binance**:
    - A API Key utilizada opera sob os princípios de menor privilégio: modo estritamente Read-Only, restrição por IP (IP restriction) vinculada ao PC Forte, sem permissão de trading, sem permissão de saques (*no withdrawals*) e sem transferências.
  - **Sigilo Patrimonial no Repositório**:
    - Nenhum valor nominal, quantidade de moedas, saldo ou identificador sensível foi inserido no repositório Git, documentação ou logs, preservando confidencialidade total.
- **Motivo**: Consolidar formalmente a validação operacional da camada privada da Binance em produção, garantindo estabilidade e aderência total aos protocolos de segurança antes do início dos estudos de governança de execução na Fase 8.3.

---

### D032 — Live Execution Safety Foundation (Fase 8.3)
- **Status**: Aceito
- **Data**: FASE 8.3
- **Contexto**: Com a validação read-only da Binance Spot concluída na Fase 8.2C, o FinBot precisa estabelecer a fundação de segurança preventiva antes de qualquer futura capacidade de envio de ordens. O envio de ordens reais envolve riscos severos (erros de precisão, ordens abaixo do lote mínimo ou notional mínimo da exchange, saldo insuficiente, falha de integridade, ordens acidentais de grande porte). O princípio constitucional do projeto estabelece: antes de ensinar o FinBot a enviar uma ordem, ele deve conseguir provar deterministicamente que uma intenção de ordem é válida, segura, limitada, autorizada e fail-closed.
- **Decisão**:
  - **Fluxo Categórico com Separação Estrita de Responsabilidades**:
    ```text
    SIGNAL
      ↓
    ORDER INTENT
      ↓
    RISK ENGINE
      ↓
    MARKET FILTER GUARD
      ↓
    STATE RECONCILIATION
      ↓
    LIVE SAFETY GATE
      ↓
    APPROVED INTENT  (ou REJECTED INTENT)
    ```
    - **Regra Fundamental: `APPROVED INTENT != EXECUTED ORDER`**. Uma intenção aprovada representa apenas a validação formal de elegibilidade. O FinBot **NÃO** executa ordens na Fase 8.3; `create_order()` e `cancel_order()` permanecem categoricamente bloqueados levantando `LiveTradingBlockedError`.
  - **OrderIntent Imutável**:
    - Dataclass frozen (`symbol`, `side`, `order_type`, `quantity`, `price`, `requested_notional`, `strategy_name`, `strategy_version`, `signal`, `created_at`, `correlation_id`).
    - Validação estrutural rigorosa no construtor: campos obrigatórios, valores numéricos finitos e positivos, rejeição imediata de `NaN` e infinitos.
    - Representa estritamente uma **intenção de dados**, sem referências à exchange e sem capacidade de envio de ordens.
  - **MarketFilterGuard (Filtros de Mercado Binance Spot)**:
    - Extração dinâmica de filtros de mercado baseada em metadados normalizados do CCXT (`limits` e `precision`), recorrendo a `info.filters` (`LOT_SIZE`, `PRICE_FILTER`, `MIN_NOTIONAL`, `NOTIONAL`) apenas como fallback documentado.
    - Proibição absoluta de hardcoding de valores da Binance (sem fixar 5 USDT, 10 USDT, tickSize ou stepSize no código).
    - Funções puras em `Decimal` para cálculo financeiro preciso: `sanitize_amount`, `sanitize_price`, `validate_notional`.
    - Truncamento estrito para passos válidos (`units = amount // amount_step; sanitized = units * amount_step`).
    - **Regra Anti-Exposição**: Nunca inflar silenciosamente uma ordem para alcançar o mínimo. Se a quantidade truncada ou o notional estiverem abaixo do mínimo exigido pelo mercado, a ordem é rejeitada (`BELOW_MIN_AMOUNT` / `BELOW_MIN_NOTIONAL`).
  - **StateReconciler e AccountStateSnapshot**:
    - Estrutura imutável `AccountStateSnapshot` contendo saldos livres e bloqueados para os ativos base e quote do símbolo avaliado.
    - Reconciliação passiva e defensiva: ordens BUY exigem saldo disponível suficiente de `quote_asset`; ordens SELL exigem saldo disponível suficiente de `base_asset`.
    - Se saldo insuficiente ou snapshot ausente: rejeição imediata (`INSUFFICIENT_QUOTE_BALANCE`, `INSUFFICIENT_BASE_BALANCE`, `MISSING_ACCOUNT_STATE`).
    - **Proibição de Correção Automática**: O reconciliador nunca realiza vendas automáticas, nunca cria posições sintéticas e nunca altera saldos.
  - **Soberania Absoluta do Risk Engine Existente**:
    - O `LiveSafetyGate` não duplica nem substitui o Risk Engine (`src/finbot/risk.py`).
    - Se o Risk Engine rejeitar (`allowed=False`), o `LiveSafetyGate` rejeita imediatamente sem possibilidade de override, bypass ou flags como `force=true`.
  - **Hard Live Limit Operacional (`live_max_order_notional`)**:
    - Limite financeiro defensivo adicional (default conservador: 100 USDT) configurável via `FINBOT_LIVE_MAX_ORDER_NOTIONAL`.
    - Se o valor nocional da ordem ultrapassar esse teto, rejeita imediatamente (`EXCEEDS_LIVE_MAX_NOTIONAL`). A ordem nunca é truncada silenciosamente para caber no limite.
  - **Autorização Operacional Explícita (`live_trading_acknowledged`)**:
    - Flag booleano configurável via `FINBOT_LIVE_TRADING_ACKNOWLEDGED`, com **default obrigatório `False`**.
    - Para uma ordem futura ser elegível, ambos `trading_mode == 'live'` e `live_trading_acknowledged == True` são exigidos.
    - Mesmo com ambos ativos, a ordem **AINDA NÃO É ENVIADA**, pois a Fase 8.3 não possui executor.
  - **Semântica de AccountStatus / API Permissions da Binance**:
    - Investigação formal dos endpoints da Binance/CCXT revelou que os campos `canTrade`, `canWithdraw`, `canDeposit` do endpoint `/api/v3/account` (CCXT `get_account_status()`) representam o status da **conta mestra** (KYC/AML do usuário), e **NÃO** as permissões granulares da chave de API HMAC específica.
    - Na Fase 8.2C, `can_withdraw` retornou `True` mesmo com saques totalmente desabilitados nas configurações da API Key.
    - **Conclusão e Decisão**: `can_trade`/`can_withdraw` de `AccountStatus` **NÃO DEVEM** ser utilizados como mecanismo de autorização da chave de API no FinBot. A proteção de permissões de chave reside externamente na Binance (leitura estrita, restrição de IP), enquanto internamente o FinBot aplica travas fail-closed independentes.
  - **Auditoria Local Segura (`LiveSafetyAuditStorage`)**:
    - Registro append-only em SQLite (`live_safety_decisions`) contendo apenas metadados operacionais não sensíveis (`correlation_id`, `timestamp`, `symbol`, `side`, `requested_notional`, `normalized_notional`, `decision`, `reason_code`).
    - Proibição estrita de gravação de API keys, API secrets ou quaisquer credenciais privadas.
  - **Inviolabilidade de Execução Real**:
    - `BinancePrivateExchange.create_order()` e `cancel_order()` permanecem com `LiveTradingBlockedError`.
    - Nenhum novo método (`submit_order`, `send_order`, `execute_order`) foi criado.
    - Prova arquitetural sentinela formalizada no teste `test_phase_8_3_cannot_submit_real_orders`.
- **Motivo**: Construir a barreira de proteção de execução mais rigorosa e determinística possível, garantindo que quando o módulo de envio de ordens for implementado em fases futuras, nenhuma ordem inválida, não-autorizada ou financeiramente excessiva possa atingir o livro de ofertas da exchange.

---

### D033 — Dry-Run Live Execution Engine (Fase 8.4A)
- **Status**: Aceito
- **Data**: FASE 8.4A
- **Contexto**: Com a fundação de segurança preventiva estabelecida na Fase 8.3 (`MarketFilterGuard`, `OrderIntent`, `LiveSafetyGate`, `StateReconciler`), o FinBot necessita de um pipeline de execução completo para validação operacional sem enviar ordens reais à Binance Spot. É crucial diferenciar os papéis e assegurar que nenhum efeito financeiro real ocorra nesta fase.
- **Decisão**:
  - **Separação Conceitual Fundamental**:
    - **`APPROVED ORDER INTENT != REAL ORDER`**: A aprovação emitida pelo `LiveSafetyGate` atesta apenas conformidade estática com regras de risco, filtros de mercado e saldo; ela **não** constitui nem autoriza envio real à exchange.
    - **`DRY_RUN != PAPER TRADING`**: O *Paper Trading* simula dinamicamente a evolução patrimonial e posições abertas ao longo do tempo (ciclos recorrentes de 1m). O *Dry-Run Execution Engine* valida estritamente a integridade do pipeline técnico de submissão (serialização canônica de payload, idempotência local, limites e precisão da exchange) **sem preenchimento financeiro (fill) e sem mutação patrimonial**.
  - **Módulo Isolado de Execução (`src/finbot/execution.py`)**:
    - `DryRunExecutionEngine`: componente dedicado que consome **exclusivamente** `ApprovedOrderIntent`. Qualquer tentativa de submeter `OrderIntent` cru, `RejectedOrderIntent` ou estruturas arbitrárias resulta em rejeição fail-closed imediata (`InvalidExecutionIntentError`).
  - **Modos de Execução (`ExecutionMode`) e Bloqueio de LIVE**:
    - Enum explícito: `ExecutionMode.DRY_RUN` e `ExecutionMode.LIVE`.
    - O modo `ExecutionMode.LIVE` é expressamente bloqueado nesta fase, levantando `LiveExecutionBlockedError`.
  - **Estrutura Imutável de Resultado (`DryRunOrderResult`)**:
    - Campos canônicos: `correlation_id`, `client_order_id`, `symbol`, `side`, `order_type`, `quantity`, `price`, `notional`, `status`, `created_at`, `safety_reason`, `execution_mode`, `order_payload`.
    - `status` utiliza valores semanticamente explícitos: `SIMULATED_ACCEPTED` e `DUPLICATE_INTENT`.
    - O status `FILLED` é categoricamente proibido em modo Dry-Run via validação no construtor.
  - **Geração Determinística de `clientOrderId` (`generate_client_order_id`)**:
    - Derivado deterministicamente a partir do `correlation_id` via hash SHA-256 truncado: `f"finbot_{sha256(correlation_id)[:28]}"` (35 caracteres).
    - Obedece estritamente às especificações da Binance Spot (`length <= 36`, caracteres permitidos `[a-zA-Z0-9-_]`).
    - Mesma correlação gera o mesmo ID; correlações diferentes geram IDs distintos; não expõe dados sensíveis.
  - **Idempotência e Persistência Local (`DryRunStorage`)**:
    - Persistência em tabela SQLite `dry_run_orders` (`correlation_id` como PRIMARY KEY).
    - Verificação prévia antes de qualquer processamento: intenções duplicadas retornam `DryRunOrderResult` com status `DUPLICATE_INTENT`, sem gerar segunda execução lógica.
    - Persistência sobrevive a reinicializações de processo e não armazena credenciais ou segredos.
  - **Construtor de Payload Canônico (`build_order_payload`)**:
    - Função pura que produz a estrutura idêntica à que futuramente será entregue ao adapter CCXT (`symbol`, `type`, `side`, `amount`, `price`, `params: {"clientOrderId": ...}`).
    - Preserva precisão decimal sem float intermediário inseguro.
    - Não conhece nem acessa `CredentialProvider`, API Keys ou rede.
  - **Orquestrador de Pipeline (`run_dry_run_pipeline`)**:
    - Fluxo: `OrderIntent -> LiveSafetyGate -> ApprovedOrderIntent -> DryRunExecutionEngine`.
    - Se o gate rejeitar: o engine **nunca** é invocado.
  - **Inviolabilidade de Trading Real**:
    - `BinancePrivateExchange.create_order()` e `cancel_order()` continuam bloqueados levantando `LiveTradingBlockedError`.
    - Zero chamadas HTTP a endpoints de negociação; validação comprovada pelo teste sentinela `test_phase_8_4a_has_zero_live_order_capability`.
- **Motivo**: Construir e auditar integralmente o mecanismo técnico de submissão de ordens antes de qualquer exposição real a capital ou livro de ofertas, provando determinismo, idempotência e conformidade regulatória da exchange.

---

### D034 — Guarded Live Order Execution Foundation (Fase 8.4B)
- **Status**: Aceito
- **Data**: FASE 8.4B
- **Contexto**: Com o motor Dry-Run concluído na Fase 8.4A, é necessário estabelecer a arquitetura formal do executor LIVE para futuras operações na Binance Spot. Contudo, a Fase 8.4B **não autoriza nenhuma ordem real**. O executor live deve existir arquiteturalmente e ser 100% testável em ambiente hermético (in-memory/fake), mantendo-se operacionalmente bloqueado contra qualquer envio acidental à API de negociação da Binance.
- **Decisão**:
  - **Evolução Arquitetural em Camadas com Defesa em Profundidade**:
    ```text
    Strategy
       ↓
    OrderIntent
       ↓
    Risk Engine
       ↓
    MarketFilterGuard
       ↓
    StateReconciler
       ↓
    LiveSafetyGate
       ↓
    ApprovedOrderIntent
       ↓
    Execution Engine
       ├── DRY_RUN → DryRunExecutionEngine
       └── LIVE    → GuardedLiveExecutionEngine
                         ↓
                    ExchangeOrderAdapter
                         ↓
                    BinancePrivateExchange
                         ↓
                     [BLOCKED IN 8.4B]
    ```
  - **GuardedLiveExecutionEngine Exclusivo para `ApprovedOrderIntent`**:
    - O executor aceita **unicamente** instâncias válidas de `ApprovedOrderIntent`.
    - Qualquer tentativa de submeter `OrderIntent` cru, `RejectedOrderIntent` ou tipos inválidos resulta em rejeição imediata fail-closed (`InvalidExecutionIntentError`).
    - Não duplica as responsabilidades do `LiveSafetyGate` ou do `Risk Engine`.
  - **Triple Live Arming (Tripla Chave de Armamento)**:
    - Três condições independentes e cumulativas necessárias para qualquer execução em modo live:
      1. `trading_mode == 'live'`
      2. `live_trading_acknowledged == True`
      3. `live_execution_enabled == True` (Default mandatório: `False`)
    - Se qualquer uma dessas condições for falsa, a submissão é rejeitada imediatamente com `LiveExecutionArmingError`.
  - **Micro-Order Cap Dedicado (`live_micro_order_max_notional`)**:
    - Separação estrita entre `live_max_order_notional` (limite geral do `LiveSafetyGate`, default 100 USDT) e `live_micro_order_max_notional` (teto específico para homologação de micro-ordens, default conservador: 15.0 USDT).
    - Se o valor nocional da ordem exceder `live_micro_order_max_notional`, a ordem é categoricamente **REJEITADA** (`MicroOrderCapExceededError`).
    - **Regra de Não-Interferência**: Nunca reduzir, truncar ou alterar o tamanho da ordem automaticamente para caber no teto.
  - **Injeção Explícita de Dependência (`ExchangeOrderAdapter`)**:
    - Interface/Protocolo formal `ExchangeOrderAdapter` desacoplando o executor de clientes de rede específicos (`submit_order`, `cancel_order`, `fetch_order_status`).
    - `FakeExchangeOrderAdapter` implementado para testes unitários herméticos e simulação controlada de timeouts, recusas e preenchimentos.
    - O `GuardedLiveExecutionEngine` **somente opera com adapter explicitamente injetado** no construtor. Ele **não** instancia nem cria implicitamente instâncias de `BinancePrivateExchange`, eliminando qualquer caminho acidental de rede.
  - **Trava Final da Fase (`RealOrderSubmissionBlockedError`)**:
    - Estrutura concreta `BinanceOrderAdapter` preparada para a futura integração na Fase 8.4C, porém protegida por trava adicional: `real_order_submission_enabled` (Default: `False`).
    - Na Fase 8.4B, qualquer chamada a `BinanceOrderAdapter.submit_order` ou `cancel_order` levanta imediatamente `RealOrderSubmissionBlockedError` **antes** de qualquer contato com o CCXT ou chamada de rede.
    - `BinancePrivateExchange.create_order()` e `cancel_order()` permanecem bloqueados levantando `LiveTradingBlockedError`.
    - Prova sentinela formalizada em `test_phase_8_4b_cannot_reach_real_binance_order_endpoint`, demonstrando que mesmo se todas as flags de configuração de LIVE forem configuradas como `True`, a barreira final da fase impede qualquer tráfego HTTP.
  - **Princípio Soberano de Falha Ambígua (`UNKNOWN != FAILED` e `TIMEOUT != SAFE TO RETRY`)**:
    - Em sistemas distribuídos financeiros, um timeout, reset de conexão ou resposta perdida após o envio da requisição não significa que a ordem falhou; ela pode ter sido recebida e aceita pelo livro de ofertas da exchange.
    - O FinBot adota o axioma:
      ```text
      TIMEOUT / NETWORK ERROR
                 ↓
          STATUS = UNKNOWN
                 ↓
      NUNCA REENVIAR AUTOMATICAMENTE
                 ↓
      RECONCILE BY CLIENT ORDER ID
                 ↓
         DECISÃO EXPLÍCITA
      ```
    - É terminantemente proibido qualquer mecanismo de retry automático cego após exceção de submissão.
  - **Máquina de Estados de Ciclo de Vida da Ordem (`OrderStatus`)**:
    - Estados formais: `PREPARED`, `PENDING_SUBMISSION`, `SUBMITTED`, `ACKNOWLEDGED`, `PARTIALLY_FILLED`, `FILLED`, `CANCEL_PENDING`, `CANCELED`, `REJECTED`, `UNKNOWN`.
    - Antes de qualquer submissão ao adapter, o estado inicial `PENDING_SUBMISSION` é persistido obrigatoriamente no banco local com `correlation_id` e `client_order_id`.
    - Idempotência local estrita: intenções duplicadas por `correlation_id` ou `client_order_id` são bloqueadas antes de qualquer nova submissão.
  - **Reconciliação e Cancelamento Controlado**:
    - `reconcile_order(client_order_id)`: consulta o adapter via `client_order_id` e atualiza deterministicamente o estado local.
    - `cancel_order(client_order_id)`: exige que a ordem seja conhecida e esteja em estado cancelável (`SUBMITTED`, `ACKNOWLEDGED`, `PARTIALLY_FILLED`). Bloqueia o cancelamento se a ordem já estiver `FILLED`, `CANCELED` ou `REJECTED`. Se a ordem estiver em estado `UNKNOWN`, exige reconciliação prévia antes de qualquer tentativa de cancelamento (`AmbiguousExecutionError`).
  - **Auditoria Local Segura (`LiveOrderStorage`)**:
    - Persistência em SQLite append-only nas tabelas `live_orders` e `live_order_lifecycle`.
    - Cada transição de estado registra `correlation_id`, `client_order_id`, `previous_status`, `new_status`, `timestamp` e `reason`.
    - Proibição absoluta de armazenamento de API Keys, API Secrets ou senhas no banco, logs ou representações de string (`repr`).
- **Motivo**: Estabelecer a infraestrutura do executor live mais defensiva, auditável e determinística possível, blindando o capital contra falhas de rede, ordens fantasmas e duplicações acidentais antes da realização da primeira micro-ordem assistida.

---

### D035 — Comando Operacional de Pre-Flight e Validação Hermética de Prontidão (Fase 8.4C1A)
- **Status**: Aceito
- **Data**: FASE 8.4C1A
- **Contexto**: A realização de uma futura micro-operação real assistida na Binance Spot (Fase 8.4C) exige um procedimento operacional unificado, seguro e reproduzível para verificar credenciais, conectividade privada, metadados públicos de mercado, saldo disponível e integridade de barreiras antes de qualquer interação humana no livro de ofertas. Essa verificação deve ocorrer via comando direto (`python -m finbot.preflight`) e ser estruturalmente incapaz de emitir ou cancelar ordens reais.
- **Decisão**:
  - **Divisão Metodológica da Fase 8.4C1**:
    - **FASE 8.4C1A**: Implementação e testes herméticos do entrypoint `finbot.preflight` no Notebook (desenvolvimento), com zero chamadas privadas reais de rede e 100% de cobertura com mocks e stubs.
    - **FASE 8.4C1B**: Execução operacional do comando em modo estritamente read-only no PC Forte (produção), onde residem as credenciais oficiais no Windows Credential Manager.
  - **Inviolabilidade de Execução Real no Pre-Flight**:
    - O comando `run_preflight` é concebido para ser estruturalmente desprovido de qualquer rota para chamadas HTTP de negociação (`create_order`, `cancel_order`).
    - Nenhuma chamada a `BinanceOrderAdapter.submit_order` ou `cancel_order` real é permitida.
    - A simulação de conformidade de pipeline ocorre obrigatoriamente através do `DryRunExecutionEngine` com armazenamento em memória (`:memory:`), emitindo `SIMULATED_ACCEPTED`.
  - **Higienização Absoluta de Saída e Proteção de Segredos**:
    - Relatório estritamente sanitizado: proibição total de exibição de API Key, API Secret, comprimentos de chave ou repr de objetos de credencial.
    - Consulta de saldos restrita a atestar `PRIVATE_BALANCE_READ = PASS` e checar passivamente suficiência (`FUNDS_AVAILABLE_FOR_CANDIDATE = YES/NO`). Proibição de exibição de saldos em USDT, BTC ou patrimônio consolidado no terminal ou em logs.
  - **Cálculo Dinâmico de Micro-Ordem Candidata (`calculate_micro_order_candidate`)**:
    - Função pura que calcula dinamicamente quantidade, preço e notional para uma compra a partir dos filtros vigentes de `BTC/USDT` no CCXT.
    - Regras estritas: conformidade com `minNotional`, `minQty`, `stepSize`, `price_step`, inclusão de margem defensiva (~15% acima do mínimo para tolerar volatilidade) e teto inviolável dado por `live_micro_order_max_notional` (default 15.0 USDT). Se os filtros exigirem um mínimo superior ao teto, emite `SAFE_MICRO_ORDER_POSSIBLE = NO`.
  - **Critério Rígido de Prontidão (`READY_FOR_8_4C2 = YES`)**:
    - Prontidão para a Fase 8.4C2 condicionada ao sucesso simultâneo de 11 verificações: credenciais presentes, autenticação privada válida, saldos lidos com sucesso, metadados obtidos, filtros válidos, candidata calculável, fundos suficientes, simulação dry-run aceita, barreira final ativa (`real_order_submission_enabled == False`), barreira de create_order ativa e barreira de cancel_order ativa.
- **Motivo**: Prover um gate de segurança operacional infalível e reproduzível que garanta conformidade técnica total antes de qualquer operação financeira real assistida.

---

### D036 — Binance Spot Testnet Integration & Production Isolation (Fase 8.4C2A)
- **Status**: Aceito
- **Data**: FASE 8.4C2A
- **Contexto**: A validação do pipeline de ordens reais da Binance Spot antes de qualquer micro-operação com dinheiro real exige um ambiente de testes realista, que emita ordens de teste na infraestrutura oficial da exchange sem comprometer recursos patrimoniais. Essa integração deve manter isolamento absoluto em relação ao ambiente de produção (`api.binance.com`), garantindo que Produção continue read-only, com trading desabilitado e blindada contra erros de configuração ou humanos.
- **Decisão**:
  - **Conceito Explícito de Ambiente (`BinanceEnvironment`)**:
    - Criação do enum `BinanceEnvironment` com valores `PRODUCTION = "production"` e `SPOT_TESTNET = "spot_testnet"`.
    - Proibição de booleanos ambíguos (ex.: `test=True`). `BinanceEnvironment.PRODUCTION` permanece como default seguro inviolável.
  - **Isolamento de Credenciais no Windows Credential Manager**:
    - Target de Produção: `FinBot/Binance/Production` (permanece estritamente read-only).
    - Target de Testnet: `FinBot/Binance/SpotTestnet` (armazenamento independente para chaves geradas em `testnet.binance.vision`).
    - Nenhuma credencial de produção pode ser reaproveitada na Testnet e nenhuma credencial de testnet pode ser usada em produção.
    - Provedor nativo parametrizado via `WindowsCredentialProvider.for_environment(env)`.
  - **GUI e CLI Seguras com Seleção Visual Clara**:
    - `credentials_gui.py` e `credentials.py` adaptados com seletor explícito de ambiente (`BINANCE PRODUCTION` vs `BINANCE SPOT TESTNET`), exibindo em tempo real o target ativo e suas permissões para evitar qualquer erro de digitação ou seleção por parte do operador.
  - **Adapter Dedicado Spot Testnet (`BinanceSpotTestnetOrderAdapter`)**:
    - Implementação de adapter conforme o protocolo `ExchangeOrderAdapter`.
    - Ativação obrigatória de sandbox no CCXT via `exchange.set_sandbox_mode(True)` imediatamente após a instanciação, antes de qualquer requisição à rede.
    - Suporte a leitura de saldos (`get_balances`), metadados (`load_markets`), submissão (`submit_order`), consulta determinística (`fetch_order`) e cancelamento (`cancel_order`).
  - **Sentry Defensivo Pré-Escrita**:
    - Função `verify_testnet_endpoint` executada antes de qualquer operação de escrita (`submit_order`, `cancel_order`).
    - Verifica que a URL do CCXT contém `testnet.binance.vision` e que NUNCA contém `api.binance.com`. Se houver qualquer divergência, a operação é sumariamente abortada com `TestnetSentryError` (fail-closed).
    - `BinanceOrderAdapter` de produção continua com sua barreira incondicional ativa (`RealOrderSubmissionBlockedError`).
  - **Armamento Independente da Testnet**:
    - Execução na Testnet exige `binance_environment == SPOT_TESTNET` e `testnet_execution_enabled == True`.
    - Flags de produção (`live_execution_enabled`, `live_trading_acknowledged`) NÃO liberam a Testnet.
    - Flags de testnet (`testnet_execution_enabled`) NÃO liberam Produção.
  - **Reutilização Integral do Pipeline de Segurança**:
    - O fluxo permanece idêntico: `OrderIntent -> Risk Engine -> MarketFilterGuard -> LiveSafetyGate -> ApprovedOrderIntent -> GuardedLiveExecutionEngine -> BinanceSpotTestnetOrderAdapter -> Binance Testnet`.
    - Preservados: micro-order cap (15 USDT), idempotência determinística, `clientOrderId` determinístico, tratamento de falha ambígua (TIMEOUT -> `UNKNOWN`), proibição de auto-retry cego e reconciliação mandatória.
  - **Comando Operacional Testnet Pre-Flight (`python -m finbot.testnet_preflight`)**:
    - Entrypoint para conferência 100% read-only de credenciais de Testnet, autenticação, saldos, filtros, integridade de barreiras e isolamento de produção, finalizando com o veredito `READY_FOR_TESTNET_ORDER = YES/NO`.
    - Zero ordens enviadas ou canceladas durante a execução do comando.
  - **Reorganização de Marcos do Roadmap**:
    - `FASE 8.4C1A`: Implementação e testes do comando de Pre-Flight (Concluída).
    - `FASE 8.4C1B`: Execução operacional do Pre-Flight Read-Only no PC Forte (Concluída).
    - `FASE 8.4C2A`: Spot Testnet Foundation e isolamento de produção (Concluída).
    - `FASE 8.4C2B`: Spot Testnet Operational Validation (Em validação operacional).
    - `FASE 8.4C3`: Assisted Production Micro-Order Validation (Pendente).
- **Motivo**: Permitir a validação ponta a ponta do pipeline real de ordens da Binance em ambiente oficial de sandbox com dinheiro fictício, eliminando qualquer risco de perda financeira e preservando a segurança de Produção.

---

### D037 — Assisted Spot Testnet Order Validation & Institutional Live Capital Gate Policy (Fase 8.4C2B)
- **Status**: Aceito
- **Data**: FASE 8.4C2B
- **Contexto**: A conclusão da Fase 8.4C2A e a aprovação com 100% de sucesso do preflight oficial contra a Binance Spot Testnet (`READY_FOR_TESTNET_ORDER = YES`) habilitam o projeto a construir a ferramenta operacional para a primeira emissão de ordem assistida em ambiente sandbox com saldo fictício. Paralelamente, surge a necessidade de estabelecer uma diretriz constitucional institucional sobre a transição de sandbox/testnet para capital real em Produção.
- **Decisão**:
  - **Comando Operacional Controlado (`python -m finbot.testnet_order_validation`)**:
    - **Modo Padrão (Read-Only / Preview)**: Quando invocado sem argumentos de confirmação, o comando opera estritamente em modo de visualização prévia (Dry Preview). Realiza a leitura de mercado, obtém filtros e preço de referência, calcula a ordem candidata (~6 USDT), verifica passivamente o Risk Engine, valida filtros via MarketFilterGuard e atesta isolamento de produção. Emite `TESTNET_WRITE_EXECUTED = NO` e `READY_TO_EXECUTE_TESTNET_ORDER = YES`, abortando antes de qualquer operação de escrita.
    - **Armamento Explícito e Inequívoco**: A submissão da ordem de teste exige a flag explícita `--confirm-testnet-order`. Flags genéricas (`--yes`, `--force`, `--live`) NÃO autorizam escrita e são terminantemente rejeitadas.
  - **Sentries Defensivos Pré-Escrita (Fail-Closed)**:
    - Imediatamente antes de submeter a ordem, o sentry re-valida:
      1. `BinanceEnvironment == SPOT_TESTNET`
      2. `testnet_execution_enabled == True`
      3. `adapter == BinanceSpotTestnetOrderAdapter` (ou fake em testes)
      4. `endpoint` contém `testnet.binance.vision` e JAMAIS `api.binance.com`
      5. `target` de credenciais é estritamente `FinBot/Binance/SpotTestnet` (rejeitando sumariamente `FinBot/Binance/Production`)
    - Qualquer divergência aborta a operação imediatamente com `TestnetSentryError`.
    - Emissão da confirmação final: `TARGET_ENVIRONMENT = BINANCE_SPOT_TESTNET`, `PRODUCTION_TARGET = NO`, `TESTNET_WRITE_ARMED = YES`.
  - **Preservação Integral do Pipeline de Segurança**:
    - A ordem percorre estritamente: `OrderIntent -> Risk Engine -> MarketFilterGuard -> LiveSafetyGate -> ApprovedOrderIntent -> GuardedLiveExecutionEngine -> BinanceSpotTestnetOrderAdapter -> Binance Spot Testnet`.
    - Sem atalhos ou desvios de esteira.
  - **Cálculo Dinâmico de Ordem Candidata**:
    - Símbolo `BTC/USDT`, lado `BUY`, tipo `MARKET`.
    - Notional calculado dinamicamente em ~6.00 USDT fictícios (com margem sobre `minNotional` e estritamente abaixo do `micro_order_cap` de 15.0 USDT). Quantidade arredondada para passo exato (`stepSize`) e validada contra `minQty`.
  - **Idempotência, Falha Ambígua e Reconciliação**:
    - `clientOrderId` determinístico no formato `finbot_<hash>`, persistência prévia de `PENDING_SUBMISSION`.
    - Falhas de rede ou timeouts resultam estritamente no estado `UNKNOWN` sem retry automático de submissão.
    - Reconciliação mandatória via polling limitado por `clientOrderId`.
  - **Política Constitucional Institucional de Capital Real (`LIVE_CAPITAL_GATE`)**:
    - **DINHEIRO REAL NÃO SERÁ UTILIZADO APENAS PORQUE O PIPELINE TÉCNICO ESTÁ PRONTO.**
    - A prontidão técnica do pipeline de execução não confere nem implica autorização de uso de capital real.
    - Antes de qualquer escrita em ambiente de Produção (`PRODUCTION`), será obrigatória a aprovação em um futuro gate formal de governança: o `LIVE_CAPITAL_GATE`.
    - O `LIVE_CAPITAL_GATE` será condicionado à estabilidade operacional comprovada em execução autônoma contínua, consistência em ambiente simulado e evidência estatística de desempenho robusto sem anomalias.
- **Motivo**: Garantir segurança máxima e governança institucional blindada na execução de ordens na Testnet e vedar terminantemente o uso precipitado de fundos reais.

---

### D038 — Binance Spot Testnet Execution Lifecycle Validation & Live Capital Gate Framework (Fase 8.4C2C)
- **Status**: Aceito
- **Data**: FASE 8.4C2C
- **Contexto**: A conclusão bem-sucedida da Fase 8.4C2B consolidou a primeira emissão e reconciliação de uma ordem real de compra na Binance Spot Testnet (`0.00008000 BTC` a ~6.63 USDT fictícios com status `FILLED` e `CONFIRMED`). Para assegurar a robustez completa do executor antes de qualquer consideração de capital real, faz-se necessário validar os demais ciclos essenciais de execução na Spot Testnet: venda a mercado (`SELL MARKET`), ordem limite longe do book (`LIMIT`) e cancelamento assistido (`CANCEL`), bem como a reconciliação precisa de todos os estados intermediários e finais.
- **Decisão**:
  - **Extensão Unificada da Ferramenta Operacional (`src/finbot/testnet_order_validation.py`)**:
    - Suporte nativo ao seletor `--action`:
      - `sell_market` (default conservador): ciclo de venda a mercado do saldo fictício adquirido.
      - `limit_cancel`: ciclo completo de colocação de ordem LIMIT abaixo do mercado seguido de cancelamento controlado e reconciliação.
      - `buy_market`: ciclo de compra a mercado (validado na 8.4C2B e mantido para testes de regressão).
  - **Modo Preview Obrigatório (100% Read-Only por Padrão)**:
    - Qualquer invocação sem a flag explícita `--confirm-testnet-order` opera em modo estritamente read-only (Dry Preview), exibindo `ENVIRONMENT`, `SYMBOL`, `SIDE`, `TYPE`, `QUANTITY`, `ESTIMATED_NOTIONAL`, `PRICE` (quando aplicável), `RISK_ENGINE`, `MARKET_FILTER_GUARD`, `PRODUCTION_ISOLATION` e `TESTNET_WRITE_EXECUTED = NO`.
    - Nenhuma escrita externa é realizada sem autorização prévia e explícita do operador.
  - **Ciclo 1: SELL MARKET Seguro com Consulta Dinâmica**:
    - O dimensionamento não presume valores fixos: consulta em tempo real o saldo disponível de BTC (`available_btc`), os filtros oficiais vigentes (`minQty`, `stepSize`, `minNotional`) e o ticker atual via `fetch_ticker`.
    - A quantidade é limitada ao teto estrito adquirido na fase anterior (`max_sell_qty = 0.00008000 BTC`), sanitizada pelo `stepSize` e validada contra `minQty`.
    - O valor nocional estimado é checado contra `minNotional` e contra o micro-order cap (15.0 USDT). Se o saldo ou notional forem insuficientes, a operação é bloqueada com segurança fail-closed (`READY_TO_EXECUTE_TESTNET_ORDER : NO`).
  - **Ciclo 2 & 3: LIMIT Order + CANCEL Controlado**:
    - Preço limite calculado deterministicamente com desconto defensivo (~15% abaixo do ticker atual do mercado), alinhado ao passo exato do livro (`price_step` / `tickSize`) para garantir que a ordem permaneça aberta no order book tempo suficiente para testar o cancelamento.
    - Notional calculado dinamicamente em ~6.00 USDT fictícios (respeitando `minNotional` de 5.0 USDT e `micro_order_cap` de 15.0 USDT).
    - Máquina de estados executada: `PREPARED` -> `PENDING_SUBMISSION` -> `SUBMITTED` -> reconciliação de estado aberto (`ACKNOWLEDGED`/`SUBMITTED`) -> verificação sentinela contra preenchimento prévio -> submissão de `CANCEL_PENDING` -> `CANCELED` -> reconciliação determinística final.
    - Se a ordem preencher na exchange antes do cancelamento (`FILLED`), o sistema detecta a transição e NÃO tenta cancelar cegamente; reconcilia e registra o estado real como preenchida.
  - **Idempotência Estrita e Prevenção de Colisões**:
    - Cada ação possui `correlation_id` e `clientOrderId` únicos e determinísticos (`finbot_<hash>`), proibindo estritamente a reutilização do correlation_id da BUY anterior.
    - Nenhuma submissão é reexecutada automaticamente em caso de timeout de rede (regra soberana: `TIMEOUT -> UNKNOWN`, auto-retry proibido).
  - **Sentries Defensivos Pré-Escrita (Fail-Closed)**:
    - Verificação obrigatória revalidada antes de qualquer submissão ou cancelamento:
      1. `binance_environment == SPOT_TESTNET`
      2. `testnet_execution_enabled == True`
      3. `adapter == BinanceSpotTestnetOrderAdapter` (ou fake em testes)
      4. `endpoint` CCXT contém `testnet.binance.vision` e JAMAIS `api.binance.com`
      5. `target` de credenciais é estritamente `FinBot/Binance/SpotTestnet` (bloqueando categoricamente `FinBot/Binance/Production`)
  - **Política Constitucional Institucional de Capital Real (`LIVE_CAPITAL_GATE`)**:
    - **PRODUCTION WRITE PERMANECE FORA DO ROADMAP OPERACIONAL IMEDIATO.**
    - Nenhum centavo de dinheiro real será arriscado apenas porque os testes de software ou de testnet passaram.
    - Antes de qualquer escrita com fundos reais na Binance Production, será mandatório o cumprimento integral do framework **`LIVE_CAPITAL_GATE`**, abrangendo:
      1. *Estabilidade Operacional*: Zero crashes, unhandled exceptions ou inconsistências de estado no ambiente do operador;
      2. *Confiabilidade de Execução*: Taxa de reconciliação de 100%, com zero ordens órfãs ou estados ambíguos não resolvidos;
      3. *Controle de Drawdown*: Drawdown estritamente dentro dos parâmetros estabelecidos pela governança de risco;
      4. *Amostragem Mínima de Operações*: Volume estatisticamente representativo de trades executados em ambiente simulado;
      5. *Resultado Líquido Positivo Após Custos*: Lucratividade comprovada descontando taxas de corretagem (taker/maker) e slippage;
      6. *Validação Fora da Amostra (Out-of-Sample)*: Robustez comprovada em dados de mercado não vistos durante a calibração de parâmetros;
      7. *Paper Trading Prolongado (Paper Soak)*: Conclusão e estabilidade demonstrada em soaking ininterrupto no PC Forte;
      8. *Testnet Soak*: Validação de resiliência a desconexões e reconexões de rede em ambiente sandbox de exchange real.
    - A fixação de valores numéricos para cada critério será objeto de uma fase específica posterior, vedada qualquer definição arbitrária antecipada.
- **Motivo**: Concluir o ciclo técnico completo de validação de ordens na Binance sem risco patrimonial e blindar constitucionalmente o projeto contra a liberação prematura de capital real.

---

### D039 — Binance Spot Testnet Soak Runner, Normalized Strategy Capital & Operational Metrics (Fase 8.4C2D)
- **Status**: Aceito
- **Data**: FASE 8.4C2D
- **Contexto**: Com as validações pontuais de execução externa na Binance Spot Testnet concluídas com sucesso na Fase 8.4C2C (BUY MARKET, SELL MARKET, BUY LIMIT e CANCEL), o projeto avança para a estruturação de infraestrutura de soaking operacional contínuo em ambiente de Testnet. Antes de iniciar qualquer operação contínua, identificou-se uma imprecisão semântica nos fills (onde ordens não executadas ou canceladas atribuíam o `limit_price` ao campo `average_price`), a necessidade de dissociar as métricas de performance do saldo fictício massivo da exchange através de um capital de estratégia normalizado (`TESTNET_STRATEGY_CAPITAL`), a estruturação de disjuntores de segurança operacionais (Circuit Breakers) automáticos para pausar novas ordens em caso de anomalias, e a criação de ferramentas read-only para visualização de status e preview sem comandos armados.
- **Decisão**:
  - **Correção da Semântica de Fills e Preservação de Preços**:
    - Se `executed_quantity == 0`, `average_price` / `average_fill_price` é estritamente `None` (ou N/A), jamais assumindo o valor de `limit_price` ou `requested_price`.
    - Preservação segregada dos campos `requested_price` / `limit_price` e `average_fill_price` em todas as estruturas (`ExchangeOrderResult`, `TestnetOrderExecutionReport`, `TestnetTradeRecord`).
    - PnL e métricas financeiras jamais contabilizam ordens não executadas ou canceladas como preenchimentos.
  - **Runner Isolado para Spot Testnet (`src/finbot/testnet_soak.py`)**:
    - Isolamento explícito e completo do Paper Runner (`paper.py`), evitando contaminação de lógica, estado ou dependências mútuas.
    - Pipeline completo e defensivo: Market Data -> Strategy -> Risk Engine -> MarketFilterGuard -> LiveSafetyGate -> GuardedLiveExecutionEngine -> BinanceSpotTestnetOrderAdapter -> Reconciliation -> Metrics & Storage.
    - Sentries invioláveis com princípio fail-closed: exige categoricamente `binance_environment == SPOT_TESTNET`, `testnet_execution_enabled == True`, domínio `testnet.binance.vision` e credenciais `FinBot/Binance/SpotTestnet`. Qualquer divergência bloqueia imediatamente a inicialização.
  - **Métricas Operacionais e Integridade em Reinício**:
    - Coleta e persistência contínua em SQLite (`data/finbot_testnet_soak.sqlite3`): `uptime_seconds`, `start_time`, `last_successful_cycle`, `total_cycles`, `successful_cycles`, `failed_cycles`, `unhandled_exceptions`, `api_errors`, `timeouts`, `reconciliations`, `unknown_orders`, `orphan_orders`, `duplicate_blocks`, `orders_created`, `orders_filled`, `orders_canceled`, `orders_rejected`, `partial_fills`.
    - Reconciliação prévia obrigatória após reinício antes de emitir qualquer nova ordem.
    - Deduplicação estrita de candles baseada no timestamp do último candle fechado processado.
    - Zero exposição de segredos, senhas ou API keys nos logs e métricas.
  - **Métricas Financeiras e Normalização de Capital (`TESTNET_STRATEGY_CAPITAL`)**:
    - Criação do conceito formal de capital normalizado da estratégia (`testnet_strategy_capital`, default 100.00 USDT), configurável e independente do saldo fictício massivo fornecido pela Binance Testnet.
    - Cálculo determinístico de métricas de rentabilidade e risco: `starting_equity`, `current_equity`, `realized_pnl`, `unrealized_pnl`, `net_pnl`, `fees`, `gross_return_pct`, `net_return_pct`, `max_drawdown_pct`, `win_rate_pct`, `loss_rate_pct`, `profit_factor`, `average_win`, `average_loss`, `expectancy`, `total_trades`, `closed_trades`.
    - Acompanhamento de qualidade amostral: `trade_sample_size`, `observation_period_seconds`, `first_trade_at`, `last_trade_at`.
  - **Disjuntores Operacionais (Safety Circuit Breakers)**:
    - Disparo automático do disjuntor (`stop_new_orders = True`) sob: ordem UNKNOWN não reconciliada, ordem órfã, falha repetida de autenticação (>=3), mismatch de endpoint/ambiente, divergência de saldo, 5 erros consecutivos, violação do Risk Engine ou falha de persistência.
    - Leitura e reconciliação continuam operacionais, mas novas ordens são estritamente proibidas até intervenção humana explícita.
  - **Ferramentas Operacionais Read-Only e Proteção Constitucional**:
    - `python -m finbot.testnet_soak_status`: comando read-only para inspeção do estado operacional e financeiro do soak.
    - `python -m finbot.testnet_soak`: por padrão opera em modo PREVIEW (Safe Mode Read-Only).
    - Proibição absoluta de flags permissivas genéricas (`--live`, `--force`, `--yes`).
    - Nenhum comando armado de execução automática fornecido nesta fase.
- **Motivo**: Assegurar integridade estatística, observabilidade total, confiabilidade operacional e proteção estrita antes do início do soaking na Testnet, sem qualquer risco a fundos reais.

---

### D040 — Testnet Soak Hardening, Heartbeat Observability, Realistic Cost Accounting & PC Forte S2 Protocol (Fase 8.4C2E)
- **Status**: Aceito
- **Data**: FASE 8.4C2E
- **Contexto**: A conclusão bem-sucedida do ciclo S1 do Testnet Soak no Notebook (02h32m04s, 134 ciclos, 8 fills, 4 trades fechados, 0 UNKNOWN, 0 órfãs, 0 erros de API, posição final NONE) confirmou a integridade funcional do pipeline em ambiente sandbox da Binance. Contudo, para preparar o sistema com segurança para uma bateria prolongada supervisionada de 24 horas (S2) no ambiente de execução dedicada (PC Forte), foi necessária a implementação de hardening rigoroso abrangendo observabilidade dinâmica de runner, graceful shutdown, restart com reconciliação prévia mandatória, segregação de taxas (exchange-reported vs estimated fallback), rastreamento determinístico de slippage por fill sem dupla contagem e preservação intangível dos dados do S1.
- **Decisão**:
  - **Observabilidade Dinâmica de Status e Heartbeat**:
    - Substituição do status estático baseado em histórico pelo cálculo dinâmico via `determine_runner_status(storage, circuit_breaker, heartbeat_timeout_seconds=180.0)`.
    - Estados possíveis:
      * `READY/IDLE`: Antes de qualquer inicialização ou quando o runner estiver inativo e sem disjuntor acionado;
      * `RUNNING`: Runner em execução ativa com heartbeat registrado no SQLite há menos de 180 segundos;
      * `STOPPED`: Runner encerrado de forma graciosa (Ctrl+C / normal) ou após expiração do heartbeat (stale runner detection);
      * `CIRCUIT_BREAKER_TRIPPED`: Disjuntor acionado, bloqueando imediatamente novas ordens.
  - **Encerramento Gracioso (Graceful Shutdown)**:
    - Implementação de runner contínuo (`run_testnet_soak_continuous`) com captura explícita de `KeyboardInterrupt`, `Ctrl+C` e sinais de encerramento.
    - Ao encerrar: marca `runner_status = "STOPPED"`, persiste `shutdown_at` e último checkpoint no SQLite, fecha conexões do banco de dados e clientes de rede de forma limpa, não emite novas ordens, preserva posições abertas válidas e preserva ordens em estado UNKNOWN para futura reconciliação.
  - **Restart Seguro e Reconciliação Prévia Mandatória**:
    - Função `reconcile_pre_cycle_state` executada estritamente ANTES de qualquer invocação da Strategy ou do Risk Engine.
    - Reconcilia todas as ordens não terminais (`PENDING_SUBMISSION`, `SUBMITTED`, `ACKNOWLEDGED`, `PARTIALLY_FILLED`, `CANCEL_PENDING`, `UNKNOWN`) com a exchange;
    - Reconstrói a posição local a partir do histórico auditado de trades;
    - Compara os saldos locais com os saldos da exchange;
    - Dispara o Circuit Breaker impedindo qualquer nova ordem caso exista ordem UNKNOWN não localizada ou divergência de saldo;
    - Nenhum CREATE de ordem é permitido antes da conclusão bem-sucedida desta validação.
  - **Contabilização Segregada e Realista de Taxas (Fees)**:
    - Segregação contábil explícita entre `EXCHANGE_REPORTED_FEES` e `ESTIMATED_FEES`.
    - Quando a exchange reportar comissão válida (`fee > 0`), o valor reportado é adotado (`fee_source = "EXCHANGE"`).
    - Quando a exchange omitir ou reportar zero (comum na Binance Testnet), aplica-se o modelo determinístico de taxa estimada fallback de 0.10% (`0.0010` do notional) sob a categoria `ESTIMATED_FEES` (`fee_source = "ESTIMATED"`).
    - Todos os valores são calculados com precisão `Decimal` e descontados integralmente no `NET_PNL`.
  - **Estimativa de Slippage por Fill e Não Duplicação**:
    - Captura do `reference_price` (preço de mercado no instante exato da intenção da ordem) e comparação com o `average_fill_price` real obtido na execução.
    - BUY Slippage: `(average_fill_price - reference_price) * executed_quantity` (adverso se positivo);
    - SELL Slippage: `(reference_price - average_fill_price) * executed_quantity` (adverso se positivo);
    - Registro de `estimated_slippage_usdt` e `estimated_slippage_bps` por trade e média ponderada por notional no snapshot financeiro;
    - **Metodologia de Não Dupla Contagem**: O `average_fill_price` já define o débito/crédito real de caixa no momento do trade; logo, o slippage atua estritamente como métrica de atrito analítico de execução e **não** é deduzido novamente do `NET_PNL`, eliminando risco de distorção matemática.
  - **Métricas Derivadas Auditadas**:
    - Garantido que ordens canceladas sem fill (`executed_quantity == 0`) são sumariamente ignoradas no PnL e contagem de trades;
    - Trades abertos permanecem isolados em `unrealized_pnl` e não entram em `closed_trades`;
    - Fills parciais são rateados proporcionalmente pelo custo de inventário;
    - Métricas `win_rate`, `profit_factor` (com teto padrão de 999.99 na ausência de perdas para compatibilidade JSON), `average_win`, `average_loss` e `expectancy` operam sobre dados reais descontando taxas.
  - **Preservação de Dados do S1 e Protocolo de Deploy S2**:
    - A base de dados do S1 (`data/finbot_testnet_soak.sqlite3`) é preservada intacta como histórico do Notebook, sendo expressamente proibido apagá-la ou sobrescrevê-la.
    - O deploy do S2 no PC Forte operará em banco próprio isolado (`data/finbot_testnet_soak_s2.sqlite3`).
    - O primeiro S2 será supervisionado (sem serviço em background ou Task Scheduler automático).
- **Motivo**: Blindar a robustez operacional, fidedignidade contábil e resiliência de restart do sistema antes da execução de 24 horas no ambiente definitivo de hardware.


